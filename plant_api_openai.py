"""
Ejemplo mínimo: servidor Flask que consulta OpenAI (function-calling)
Devuelve JSON: {humedad_tierra: int, humedad_ambiente: int, tipo: "interior"|"exterior"}

Uso:
  - export OPENAI_API_KEY=sk_...
  - python plant_api_openai.py

No almacenes la API key en el ESP; despliega este servicio en un host seguro
(y actualiza la URL en el firmware).
"""

from flask import Flask, request, jsonify
import json
import os
import openai

app = Flask(__name__)
openai.api_key = os.environ.get("OPENAI_API_KEY")
if not openai.api_key:
    raise RuntimeError("Set OPENAI_API_KEY environment variable")

# Define a function schema so the model returns structured arguments
FUNCTIONS = [
    {
        "name": "get_species_info",
        "description": "Return ideal soil and ambient humidity and whether the species is indoor or outdoor",
        "parameters": {
            "type": "object",
            "properties": {
                "humedad_tierra": {"type": "integer", "description": "Ideal soil humidity percentage 0-100"},
                "humedad_ambiente": {"type": "integer", "description": "Ideal ambient humidity percentage 0-100"},
                "tipo": {"type": "string", "enum": ["interior", "exterior"], "description": "indoor or outdoor plant"}
            },
            "required": ["humedad_tierra", "humedad_ambiente", "tipo"]
        }
    }
]

@app.route('/especie', methods=['POST'])
def especie():
    data = request.get_json(force=True)
    especie = (data.get('especie') or '').strip()
    if not especie:
        return jsonify({"error": "missing 'especie' in JSON body"}), 400

    # System prompt + user instruction: ask model to be concise and return via function
    system = "You are a botanical assistant that gives concise ideal humidity numbers for plant species. Return only plausible numeric values between 0 and 100."
    user = f"Give the ideal soil humidity (%) and ambient humidity (%) and whether the plant is generally interior or exterior for the species: {especie}. Return via the function get_species_info as integers and the tipo as 'interior' or 'exterior'. If uncertain, choose a conservative value and prefer to mark as 'interior' if ambiguous."

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo-0613",
            messages=[{"role":"system","content":system}, {"role":"user","content":user}],
            functions=FUNCTIONS,
            function_call={"name":"get_species_info"},
            temperature=0.2,
            max_tokens=200
        )

        # The model should return a function_call
        choice = resp['choices'][0]
        if 'message' in choice and choice['message'].get('function_call'):
            func_args = choice['message']['function_call'].get('arguments')
            # arguments is a JSON string; parse safely
            import json
            try:
                args = json.loads(func_args)
                # Validate ranges and types
                ht = int(args.get('humedad_tierra', -1))
                ha = int(args.get('humedad_ambiente', -1))
                tipo = args.get('tipo', '')
                # Clamp/validate
                if ht < 0 or ht > 100: ht = max(0, min(100, ht if ht!=-1 else 50))
                if ha < 0 or ha > 100: ha = max(0, min(100, ha if ha!=-1 else 50))
                tipo = 'interior' if tipo not in ['interior','exterior'] else tipo

                out = {
                    'humedad_tierra': ht,
                    'humedad_ambiente': ha,
                    'tipo': tipo
                }
                return jsonify(out), 200
            except Exception as e:
                return jsonify({"error": "failed parsing model arguments", "detail": str(e), "raw": func_args}), 500

        # Fallback: if model returned text, try to extract numbers heuristically
        text = choice['message'].get('content','')
        # Very simple heuristic extraction
        import re
        nums = re.findall(r"(\d{1,3})%?", text)
        ht = int(nums[0]) if len(nums) > 0 else 50
        ha = int(nums[1]) if len(nums) > 1 else 50
        tipo = 'interior'
        out = {'humedad_tierra': ht, 'humedad_ambiente': ha, 'tipo': tipo, 'note': 'extracted from text fallback', 'raw_text': text}
        return jsonify(out), 200

    except Exception as e:
        return jsonify({"error": "openai request failed", "detail": str(e)}), 502

@app.route('/esplanta', methods=['POST','GET'])
def esplanta():
    # Parseo robusto del cuerpo: intenta JSON silencioso, luego crudo, luego form
    data = request.get_json(silent=True)
    if data is None:
        raw = request.data or b''
        try:
            data = json.loads(raw.decode('utf-8') or '{}') if raw else {}
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}
    pregunta = (
        (data.get('pregunta') if isinstance(data, dict) else None)
        or request.form.get('pregunta')
        or request.args.get('pregunta')
        or ''
    ).strip()
    if not pregunta:
        return jsonify({"error": "missing 'pregunta' in JSON body"}), 400

    system = "Eres un asistente experto en plantas. Si la pregunta que te hacen está relacionada con plantas, jardinería, botánica, cuidados de plantas, especies vegetales, enfermedades de plantas, etc., responde solo con 'sí'. Si no tiene nada que ver con plantas, responde solo con 'no'. No añadas nada más."
    user = pregunta
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo-0613",
            messages=[{"role":"system","content":system}, {"role":"user","content":user}],
            temperature=0,
            max_tokens=2
        )
        choice = resp['choices'][0]
        text = choice['message'].get('content','').strip().lower()
        if 'sí' in text or 'si' in text or 'yes' in text:
            return jsonify({"es_planta": True}), 200
        if 'no' in text:
            return jsonify({"es_planta": False}), 200
        # fallback: if unclear, default to False
        return jsonify({"es_planta": False, "raw": text}), 200
    except Exception as e:
        return jsonify({"error": "openai request failed", "detail": str(e)}), 502

@app.route('/', methods=['GET'])
def root():
    return jsonify({"ok": True, "service": "plantagotchi", "endpoints": ["/esplanta", "/especie", "/health"]}), 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"ok": True}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
