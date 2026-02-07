import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from langchain_text_splitters import RecursiveCharacterTextSplitter
import json
import os
from dotenv import load_dotenv
import vertexai
from vertexai.language_models import TextEmbeddingModel
from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector

load_dotenv()

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
COLLECTION_NAME = os.getenv("FIRESTORE_COLLECTION", "animal_liberation_chunks")

def extract_text_from_epub(epub_path):
    book = epub.read_epub(epub_path)
    chapters = []
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            chapters.append(item.get_content())
    
    text = ""
    for html in chapters:
        soup = BeautifulSoup(html, 'html.parser')
        # Remove script and style elements
        for script_or_style in soup(["script", "style"]):
            script_or_style.decompose()
        
        # Get text and clean up whitespace
        text += soup.get_text(separator=' ') + "\n\n"
    
    return text

def chunk_text(text, chunk_size=1000, chunk_overlap=200):
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        is_separator_regex=False,
    )
    chunks = text_splitter.split_text(text)
    return chunks

def init_gcp():
    if not PROJECT_ID:
        raise ValueError("GOOGLE_CLOUD_PROJECT status no está configurado en .env")
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    db = firestore.Client(project=PROJECT_ID)
    return db

def get_embeddings(texts):
    model = TextEmbeddingModel.from_pretrained("text-embedding-004")
    embeddings = model.get_embeddings(texts)
    return [embedding.values for embedding in embeddings]

def upload_to_firestore(db, chunks):
    batch_size = 5 # Pequeño para evitar límites de Vertex AI
    collection_ref = db.collection(COLLECTION_NAME)
    
    print(f"Subiendo {len(chunks)} fragmentos a Firestore...")
    
    for i in range(0, len(chunks), batch_size):
        batch_chunks = chunks[i:i + batch_size]
        embeddings = get_embeddings(batch_chunks)
        
        for j, (text, vector) in enumerate(zip(batch_chunks, embeddings)):
            doc_id = f"chunk_{i + j}"
            doc_ref = collection_ref.document(doc_id)
            doc_ref.set({
                "text": text,
                "embedding": Vector(vector),
                "metadata": {
                    "source": "Animal Liberation Now",
                    "index": i + j
                }
            })
        print(f"Progreso: {min(i + batch_size, len(chunks))}/{len(chunks)}")

def main():
    epub_filename = "Animal Liberation Now (Peter Singer).epub"
    if not os.path.exists(epub_filename):
        print(f"Error: No se encontró el archivo {epub_filename}")
        return

    print("Extrayendo texto del EPUB...")
    text = extract_text_from_epub(epub_filename)
    print(f"Texto extraído. Creados fragmentos...")
    
    chunks = chunk_text(text)
    print(f"Creados {len(chunks)} fragmentos.")
    
    try:
        db = init_gcp()
        upload_to_firestore(db, chunks)
        print("¡Proceso completado con éxito!")
    except Exception as e:
        print(f"Error durante la integración con GCP: {e}")
        print("Asegúrate de haber configurado el .env y autenticado con 'gcloud auth application-default login'")

if __name__ == "__main__":
    main()
