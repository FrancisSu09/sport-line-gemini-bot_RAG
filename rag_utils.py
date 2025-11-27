import os
import chromadb
from google import genai
from chromadb.utils import embedding_functions

# Initialize Gemini Client
# We will use environment variables for the API key

class GeminiEmbeddingFunction(embedding_functions.EmbeddingFunction):
    def __init__(self, api_key):
        self.client = genai.Client(api_key=api_key)

    def __call__(self, input: list[str]) -> list[list[float]]:
        # Gemini embedding model: models/text-embedding-004
        # The SDK might have a slightly different signature, let's be robust
        embeddings = []
        for text in input:
            response = self.client.models.embed_content(
                model="text-embedding-004",
                contents=text,
            )
            # The response structure depends on the SDK version, 
            # but usually it has an 'embedding' attribute or similar.
            # Based on recent SDKs: response.embeddings[0].values
            # Or response.embedding.values
            # Let's try to access it safely.
            
            # If response is a list or has multiple embeddings, we take the first one since we send one by one
            # But wait, embed_content can take a list? 
            # Let's keep it simple and do one by one for safety or check docs if I could.
            # Actually, to be efficient, we should batch if possible, but let's start simple.
            
            if hasattr(response, 'embeddings') and response.embeddings:
                embeddings.append(response.embeddings[0].values)
            elif hasattr(response, 'embedding'):
                 embeddings.append(response.embedding.values)
            else:
                # Fallback or error
                print(f"Error embedding text: {text[:20]}...")
                embeddings.append([]) 
        return embeddings

def get_db_collection(collection_name="sports_knowledge"):
    """
    Get or create a ChromaDB collection with Gemini embedding function.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment variables")

    # Persistent client to save data to disk
    client = chromadb.PersistentClient(path="./chroma_db")
    
    gemini_ef = GeminiEmbeddingFunction(api_key=api_key)
    
    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=gemini_ef
    )
    return collection

def add_documents(documents: list[str], metadatas: list[dict] = None, ids: list[str] = None):
    """
    Add documents to the vector store.
    """
    collection = get_db_collection()
    
    if not ids:
        # Generate simple IDs if not provided
        ids = [f"doc_{i}" for i in range(len(documents))]
        
    if not metadatas:
        metadatas = [{"source": "manual"} for _ in documents]

    collection.add(
        documents=documents,
        metadatas=metadatas,
        ids=ids
    )

def query_db(query_text: str, n_results: int = 3) -> list[str]:
    """
    Query the database for relevant documents.
    """
    collection = get_db_collection()
    
    results = collection.query(
        query_texts=[query_text],
        n_results=n_results
    )
    
    # results['documents'] is a list of list of strings (since we passed a list of queries)
    if results and results['documents']:
        return results['documents'][0]
    return []
