"""Talk to a local LLM server (Ollama or llama.cpp's ``llama-server``) over its OpenAI-style API.

Only loopback addresses are accepted, so transaction data can never leave the machine. The
categorizer's LLM tier uses this today; the Phase 5 chat reuses the same client.
"""
