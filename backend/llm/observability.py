"""
Centralised Langfuse Observability

Provides a lazily-initialised Langfuse client (get_langfuse) used by code
that creates traces manually (e.g. the text-to-sql agent), and a shared
make_session_id() helper so the report pipeline and the chat agent can be
linked under the same Langfuse session when they relate to the same
report week.

Note: backend/llm/chain.py maintains its own separate Langfuse client
instance rather than using get_langfuse() from here. That's intentional,
not duplication to clean up — chain.py uses the @observe decorator
pattern from the Langfuse v2 SDK, which requires its own module-level
client distinct from this one's manual trace() calls. The two were kept
separate after diagnosing a real flush-timing bug; merging them risks
reintroducing it.
"""

import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

_langfuse_client = None


def get_langfuse():
    global _langfuse_client
    if _langfuse_client is not None:
        return _langfuse_client

    try:
        from langfuse import Langfuse

        pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        sk = os.getenv("LANGFUSE_SECRET_KEY", "")
        host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

        if not pk or not sk:
            print("[Langfuse] No keys configured — tracing disabled.")
            return None

        _langfuse_client = Langfuse(public_key=pk, secret_key=sk, host=host)
        print(f"[Langfuse] Client initialised → {host}")
        return _langfuse_client

    except ImportError:
        print("[Langfuse] SDK not installed.")
        return None
    except Exception as e:
        print(f"[Langfuse] Init error: {e}")
        return None


def make_session_id(week_ending: Optional[str]) -> str:
    """
    Shared session ID convention so the report pipeline trace and any
    chat agent traces about the same report week land in the same
    Langfuse session, regardless of which client created them.
    """
    if week_ending:
        return f"weekly_report_{week_ending}"
    from datetime import datetime

    return f"weekly_report_{datetime.utcnow().strftime('%Y-%m-%d')}"


def flush():
    lf = get_langfuse()
    if lf:
        try:
            lf.flush()
        except Exception as e:
            print(f"[Langfuse] flush error: {e}")
