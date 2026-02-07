import os
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import vertexai
from vertexai.language_models import TextEmbeddingModel
from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from langchain_google_vertexai import ChatVertexAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

load_dotenv()

# Configuración
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
COLLECTION_NAME = os.getenv("FIRESTORE_COLLECTION", "animal_liberation_chunks")

# Inicialización de GCP
vertexai.init(project=PROJECT_ID, location=LOCATION)
db = firestore.Client(project=PROJECT_ID)

app = FastAPI(title="EthicAI - Singer's Voice API")

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir archivos estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def serve_index():
    return FileResponse("static/index.html")

@app.get("/background.png")
async def serve_background():
    return FileResponse("static/background.png")

class QueryRequest(BaseModel):
    question: str

class QueryResponse(BaseModel):
    answer: str
    context: list[str]

def get_query_embedding(text: str):
    model = TextEmbeddingModel.from_pretrained("text-embedding-004")
    embeddings = model.get_embeddings([text])
    return embeddings[0].values

def search_vector_db(query_vector: list[float], limit: int = 5):
    collection_ref = db.collection(COLLECTION_NAME)
    
    # Búsqueda por similitud de vectores en Firestore
    vector_query = collection_ref.find_nearest(
        vector_field="embedding",
        query_vector=Vector(query_vector),
        distance_measure=DistanceMeasure.COSINE,
        limit=limit
    )
    
    docs = vector_query.stream()
    results = []
    for doc in docs:
        results.append(doc.to_dict().get("text", ""))
    return results

# Configuración de LangChain
template = """
Eres una inteligencia artificial experta en la obra de Peter Singer, específicamente en su libro "Liberación Animal". 
Tu objetivo es responder preguntas de manera noble, ética y protectora, basándote exclusivamente en el contexto proporcionado del libro.

Si la respuesta no se encuentra en el contexto, di amablemente que no tienes esa información específica en el libro, pero mantén el tono filosófico de Singer.

Contexto:
{context}

Pregunta: {question}

Respuesta:"""

prompt = PromptTemplate.from_template(template)
model = ChatVertexAI(model_name="gemini-2.0-flash-001", project=PROJECT_ID, location=LOCATION)
chain = prompt | model | StrOutputParser()

@app.post("/query", response_model=QueryResponse)
async def query_bot(request: QueryRequest):
    try:
        # 1. Generar embedding de la pregunta
        query_vector = get_query_embedding(request.question)
        
        # 2. Buscar en Firestore
        context_chunks = search_vector_db(query_vector)
        
        if not context_chunks:
            raise HTTPException(status_code=404, detail="No se encontró contexto relevante.")
        
        # 3. Generar respuesta con Gemini usando LangChain
        context_text = "\n\n".join(context_chunks)
        answer = chain.invoke({"context": context_text, "question": request.question})
        
        return QueryResponse(answer=answer, context=context_chunks)
    
    except Exception as e:
        print(f"Error en el backend: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
