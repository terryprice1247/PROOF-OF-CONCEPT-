Momentum Companion Live Brain POC v2

Files:
- companion_live_brain_poc_v2.py
- companion_quotes_sample.json
- momentum_history.json

How to test:
1. Put your real momentum_history.json in this same folder.
2. Make sure Ollama is running:
   ollama serve
3. Make sure mistral exists:
   ollama pull mistral
4. Run:
   python companion_live_brain_poc_v2.py

Fixes in v2:
- Check Tickets is ignored as a growth habit.
- Growth habits are Workout, Coding, Networking/LinkedIn, and Spanish.
- Direct time questions get direct answer rules.
- "How long on LinkedIn?" should answer with 10-20 minutes first.
- Tighter UI spacing.
