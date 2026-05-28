"""
iZACH Agents — intelligent coordinators that USE modules/ as tools.

Agents/      ← this layer: intent, reasoning, multi-step coordination
modules/     ← tool layer: Spotify, WhatsApp, system control, etc.
"""
from Agents.orchestrator import OrchestratorAgent, DOMAINS

__all__ = ["OrchestratorAgent", "DOMAINS"]
