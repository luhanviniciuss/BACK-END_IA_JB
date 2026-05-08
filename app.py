from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import os
import re
import hashlib
import google.generativeai as genai

app = Flask(__name__)
app.secret_key = "jb_secret_key_intelligence"
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

def get_db_connection():
    db_url = os.getenv("DATABASE_URL")
    if "supabase.com" in db_url and "sslmode" not in db_url:
        db_url += "&sslmode=require" if "?" in db_url else "?sslmode=require"
    return psycopg2.connect(db_url)

@app.route("/api/debug_db")
def debug_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM documentos")
        count = cur.fetchone()[0]
        cur.execute("SELECT conteudo FROM documentos WHERE conteudo ILIKE '%101%' LIMIT 1")
        sample = cur.fetchone()
        conn.close()
        return jsonify({"count": count, "sample": sample[0] if sample else "Nada"})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/ask", methods=["POST", "OPTIONS"])
def ask():
    if request.method == "OPTIONS": return jsonify({"status": "ok"}), 200
    data = request.json
    question = data.get("question")
    # Busca simplificada direta para teste
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT conteudo FROM documentos WHERE conteudo ILIKE '%101%' AND conteudo ILIKE '%fortaleza%' LIMIT 5")
        rows = cur.fetchall()
        context = "\n".join([r[0] for r in rows])
        conn.close()
    except: context = "ERRO BANCO"

    def generate():
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model = genai.GenerativeModel("gemini-flash-latest")
        prompt = f"CONTEXTO:\n{context}\n\nPERGUNTA: {question}"
        response = model.generate_content(prompt, stream=True)
        for chunk in response:
            if chunk.text: yield f"data: {json.dumps({'text': chunk.text})}\n\n"
        yield "data: [DONE]\n\n"
    return Response(generate(), mimetype="text/event-stream")

if __name__ == "__main__":
    app.run()
