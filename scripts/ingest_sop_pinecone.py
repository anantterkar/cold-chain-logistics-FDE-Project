from pathlib import Path

import pandas as pd
import pypdf
from dotenv import load_dotenv

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# NOTE: Keeping filename for backward compatibility.
# This script now builds a local FAISS index instead of Pinecone.

script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
load_dotenv(project_root / ".env")

policy_dir = project_root / "data" / "policy"
cache_dir = project_root / "data" / "cache"
index_dir = cache_dir / "sop_faiss_index"
cache_dir.mkdir(parents=True, exist_ok=True)

embedding_model = "BAAI/bge-m3"
embeddings = HuggingFaceEmbeddings(model_name=embedding_model, model_kwargs={"device": "cpu"})
text_splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=60)


def parse_policy_file(file_path: Path) -> list[Document]:
    suffix = file_path.suffix.lower()

    if suffix in {".md", ".txt"}:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        return text_splitter.split_documents([Document(page_content=text)])

    if suffix == ".pdf":
        parts: list[str] = []
        with open(file_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    parts.append(page_text)
        return text_splitter.split_documents([Document(page_content="\n".join(parts))])

    if suffix in {".csv", ".xlsx"}:
        df = pd.read_csv(file_path) if suffix == ".csv" else pd.read_excel(file_path)
        docs = []
        for _, row in df.iterrows():
            row_text = " | ".join(
                f"{col}: {val}" for col, val in row.items() if pd.notna(val) and str(val).strip()
            )
            if row_text:
                docs.append(Document(page_content=row_text))
        return text_splitter.split_documents(docs)

    return []


all_docs: list[Document] = []
for pattern in ("*.md", "*.txt", "*.pdf", "*.csv", "*.xlsx"):
    for file_path in policy_dir.glob(pattern):
        chunks = parse_policy_file(file_path)
        for chunk in chunks:
            chunk.metadata["source_file"] = file_path.name
            chunk.metadata["file_format"] = file_path.suffix.replace(".", "").upper() or "RAW"
        all_docs.extend(chunks)

if not all_docs:
    raise RuntimeError(f"No policy documents found in {policy_dir}")

print(f"Building local FAISS index from {len(all_docs)} document chunks...")
vector_store = FAISS.from_documents(all_docs, embedding=embeddings)
vector_store.save_local(str(index_dir))
print(f"Local SOP index ready at: {index_dir}")