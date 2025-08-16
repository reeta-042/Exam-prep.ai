import os
import uuid
import streamlit as st

# Import functions from their respective files
from app.chain import build_llm_chain, retrieve_hybrid_docs, rerank_documents
from app.streamlit import upload_pdfs, save_uploaded_files
from app.utility import (
    cached_chunk_pdf,
    cached_get_vectorstore,
    get_bm25_retriever_from_chunks
)

# ------------------- PAGE CONFIGURATION -------------------
st.set_page_config(
    page_title="ExamAI 📄",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)




# ------------------- API KEYS & CONSTANTS -------------------
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
PINECONE_API_KEY = st.secrets["PINECONE_API_KEY"]
PINECONE_INDEX_NAME = st.secrets["PINECONE_INDEX_NAME"]
UPLOAD_DIR = "uploaded_files"
os.makedirs(UPLOAD_DIR, exist_ok=True)





# ------------------- SIDEBAR FOR FILE UPLOADS -------------------
with st.sidebar:
    st.header("📚 Your Course Material")
    st.markdown("Upload your PDF files here. Once processed, you can ask questions in the main window.")
    
    uploaded_files, submitted = upload_pdfs()

    if submitted and uploaded_files:
        namespace = f"session_{uuid.uuid4().hex}"
        st.session_state["namespace"] = namespace

        with st.spinner("📥 Ingesting and indexing your PDFs..."):
            file_paths = save_uploaded_files(uploaded_files)
            all_chunks = []
            for path in file_paths:
                # Use the imported cached function
                chunks = cached_chunk_pdf(path)
                all_chunks.extend(chunks)
            st.session_state["all_chunks"] = all_chunks

            # Use the imported store_chunks function (assuming it's in vectorbase)
            from app.vectorbase import store_chunks
            store_chunks(all_chunks, PINECONE_API_KEY, PINECONE_INDEX_NAME, namespace)
        
        st.success(f"✅ Uploaded {len(uploaded_files)} file(s) successfully!")
        st.rerun()


# ------------------- MAIN PAGE LAYOUT -------------------
st.title("💻 ExamAI: Chat with your Course Material")

session_active = "namespace" in st.session_state and "all_chunks" in st.session_state

if not session_active:
    st.info("Please upload your documents in the sidebar to begin your study session.")

st.subheader("...Ask Away...")
query = st.text_input(
    "What do you want to know?",
    placeholder="e.g., What is the definition of data?",
    label_visibility="collapsed",
    disabled=not session_active
)


# ------------------- QUERY PROCESSING & DISPLAY -------------------
if query and session_active:
    namespace = st.session_state["namespace"]
    all_chunks = st.session_state["all_chunks"]
    vectorstore = cached_get_vectorstore(PINECONE_API_KEY, PINECONE_INDEX_NAME, namespace)
    bm25_retriever = get_bm25_retriever_from_chunks(all_chunks)

    with st.spinner("🕵️‍♂️ Searching your documents..."):
        retrieved_docs = retrieve_hybrid_docs(query, vectorstore, bm25_retriever, top_k=15)

    if not retrieved_docs:
        st.error("I couldn't find any relevant information in the documents to answer this. Please try another question.")
    else:
        with st.spinner("📚 Reranking results for relevance..."):
            reranked_docs = rerank_documents(query, retrieved_docs, top_k=5)
        if not reranked_docs:
            reranked_docs = retrieved_docs

        answer_tab, quiz_tab, context_tab = st.tabs(["💡 Answer", "📝 Quiz", "🔍 Retrieved Context"])

        input_data = {
            "context": "\n\n---\n\n".join([doc.page_content for doc in reranked_docs]),
            "question": query
        }
        answer_chain, followup_chain, quiz_chain = build_llm_chain(api_key=GOOGLE_API_KEY)

        with answer_tab:
            st.markdown("#### Main Answer")
            with st.spinner("⌨️ Generating answer..."):
                answer = answer_chain.invoke(input_data)
                st.markdown(answer)
            
            st.markdown("#### 🗨️ Follow-up Questions")
            with st.spinner("Thinking of more questions..."):
                followup = followup_chain.invoke(input_data)
                st.markdown(followup)

        with quiz_tab:
            with st.spinner("📝 Generating quiz..."):
                quiz_card = quiz_chain.invoke(input_data)
                if quiz_card:
                    for i, q in enumerate(quiz_card):
                        st.markdown(f"**Question {i+1}:** {q['question']}")
                        for label, opt in q["options"].items():
                            if opt:
                                st.markdown(f"- {label}. {opt}")
                        with st.expander("Show Answer"):
                            st.markdown(f"**✅ Correct Answer:** {q['answer']}")
                            if q["explanation"]:
                                st.markdown(f"**💡 Why?** {q['explanation']}")
                        st.markdown("---" if i < len(quiz_card) - 1 else "")
                else:
                    st.warning("⚠️ Quiz could not be generated for this topic.")

        with context_tab:
            st.markdown("These are the top chunks retrieved from your document to generate the answer.")
            for i, doc in enumerate(reranked_docs):
                st.info(f"**Chunk {i+1}:**\n\n" + doc.page_content)

