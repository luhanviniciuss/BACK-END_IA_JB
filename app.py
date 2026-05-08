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

@app.after_request
def after_request(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
    return response

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_db_connection():
    db_url = os.getenv("DATABASE_URL")
    if not db_url: return None
    if "supabase.com" in db_url and "sslmode" not in db_url:
        db_url += "&sslmode=require" if "?" in db_url else "?sslmode=require"
    return psycopg2.connect(db_url)

def get_context(query, history=None):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        clean_query = query.lower().replace("?", "").replace("!", "").replace(".", "").replace(",", "").replace("-", " ")
        words = clean_query.split()
        
        all_results = []
        search_terms = [w for w in words if len(w) > 2]
        
        # 1. BUSCA NO TREINAMENTO (APRENDIZADO ADMIN)
        cursor.execute("SELECT resposta_correta FROM treinamento_ia WHERE %s LIKE '%%' || pergunta || '%%' OR pergunta LIKE '%%' || %s || '%%'", (clean_query, clean_query))
        train_result = cursor.fetchone()
        if train_result:
            all_results.append(f"CONHECIMENTO VALIDADO POR ADMIN: {train_result['resposta_correta']}")

        # 2. BUSCA NOS DOCUMENTOS
        for w in search_terms:
            cursor.execute("SELECT conteudo FROM documentos WHERE conteudo ILIKE %s OR conteudo_limpo ILIKE %s LIMIT 15", (f"%{w}%", f"%{w}%"))
            results = cursor.fetchall()
            for r in results:
                all_results.append(r['conteudo'])
        
        conn.close()
        unique_results = list(dict.fromkeys(all_results))
        return "\n\n".join(unique_results[:12])
    except:
        return ""

@app.route("/api/login", methods=["POST", "OPTIONS"])
def login():
    if request.method == "OPTIONS": return jsonify({"status": "ok"}), 200
    data = request.json
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, username, role FROM usuarios WHERE username = %s AND password = %s", 
                       (data.get("username"), hash_password(data.get("password"))))
        user = cursor.fetchone()
        conn.close()
        if user: return jsonify({"status": "success", "user": user})
        return jsonify({"status": "error"}), 401
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/api/ask", methods=["POST", "OPTIONS"])
def ask():
    if request.method == "OPTIONS": return jsonify({"status": "ok"}), 200
    data = request.json
    question = data.get("question")
    history = data.get("history", [])
    conversa_id = data.get("conversa_id")
    
    context = get_context(question, history)

    def generate():
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model = genai.GenerativeModel("gemini-flash-latest")
        
        history_text = ""
        if history:
            history_text = "HISTÓRICO RECENTE:\n"
            for msg in history[-3:]: # Pega as últimas 3 mensagens
                role = "Gestor" if msg.get("role") == "user" else "IA"
                history_text += f"{role}: {msg.get('content', '')}\n"

        prompt = f"""
        Você é o Especialista em Logística e Processos do Grupo JB.
        
        {history_text}

        REGRAS DE RESPOSTA:
        1. Responda APENAS o que foi perguntado de forma ultra-resumida.
        2. Se pediu o motorista, dê APENAS o nome do motorista.
        3. É PROIBIDO dar introduções como "Como IA..." ou dar sugestões extras.
        4. Use o CONTEXTO abaixo para responder. Se o dado não estiver lá, diga apenas: "Informação não consta nos manuais."
        5. Sem formatações longas. Vá direto ao ponto.

        CONTEXTO DO GRUPO JB:
        {context}

        PERGUNTA: {question}
        """
        
        try:
            response = model.generate_content(prompt, stream=True)
            full_response = ""
            for chunk in response:
                if chunk.text:
                    full_response += chunk.text
                    yield f"data: {json.dumps({'text': chunk.text})}\n\n"
            
            if conversa_id:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("INSERT INTO mensagens (conversa_id, role, content) VALUES (%s, %s, %s)", 
                               (conversa_id, "assistant", full_response))
                conn.commit()
                conn.close()
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'text': str(e)})}\n\n"

    return Response(generate(), mimetype="text/event-stream")

@app.route("/api/conversations", methods=["GET", "POST", "OPTIONS"])
def conversations():
    if request.method == "OPTIONS": return jsonify({"status": "ok"}), 200
    user_id = request.args.get("user_id") or (request.json.get("user_id") if request.is_json else None)
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    if request.method == "POST":
        cursor.execute("INSERT INTO conversas (user_id, titulo) VALUES (%s, %s) RETURNING id", (user_id, request.json.get("titulo", "Conversa")))
        chat_id = cursor.fetchone()["id"]
        conn.commit()
        conn.close()
        return jsonify({"id": chat_id})
    cursor.execute("SELECT id, titulo FROM conversas WHERE user_id = %s ORDER BY id DESC", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return jsonify(rows)

@app.route("/api/messages/<int:id>")
def messages(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT role, content FROM mensagens WHERE conversa_id = %s ORDER BY id ASC", (id,))
    rows = cursor.fetchall()
    conn.close()
    return jsonify(rows)

if __name__ == "__main__":
    app.run()
