import os
import warnings
from dotenv import load_dotenv

# Całkowite wyciszenie ostrzeżeń zewnętrznych bibliotek (SDK / HTTP)
warnings.filterwarnings("ignore")

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
  raise ValueError("Brak klucza GOOGLE_API_KEY w .env!")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
  raise ValueError("Brak klucza OPENAI_API_KEY w .env!")

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
if not TAVILY_API_KEY:
  raise ValueError("Brak klucza TAVILY_API_KEY w .env!")

DEFAULT_COUNTRY = "Polska"
# Najnowszy model Gemini
DEFAULT_LLM_MODEL = "gemini-3.8-flash"
DEFAULT_OPENAI_MODEL = "gpt-4o"