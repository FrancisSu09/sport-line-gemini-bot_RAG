import os
import glob
from dotenv import load_dotenv

# Load env vars first
load_dotenv()

from rag_utils import add_documents

DATA_DIR = "./data"

def load_and_ingest():
    print(f"Scanning {DATA_DIR} for .txt files...")
    files = glob.glob(os.path.join(DATA_DIR, "*.txt"))
    
    if not files:
        print("No .txt files found.")
        return

    documents = []
    metadatas = []
    ids = []

    for file_path in files:
        print(f"Reading {file_path}...")
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                # Simple chunking by paragraphs or just whole file if small
                # For better RAG, we should chunk properly. 
                # Let's do a simple split by double newlines for now.
                chunks = content.split("\n\n")
                for i, chunk in enumerate(chunks):
                    if chunk.strip():
                        documents.append(chunk.strip())
                        metadatas.append({"source": os.path.basename(file_path), "chunk_id": i})
                        ids.append(f"{os.path.basename(file_path)}_{i}")

    if documents:
        print(f"Ingesting {len(documents)} chunks...")
        add_documents(documents, metadatas, ids)
        print("Ingestion complete!")
    else:
        print("No content to ingest.")

if __name__ == "__main__":
    # Load environment variables if needed (e.g. if running standalone)
    from dotenv import load_dotenv
    load_dotenv()
    
    load_and_ingest()
