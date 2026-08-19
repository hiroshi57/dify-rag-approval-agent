"""社内規程 RAG + 承認エージェントのコア(標準ライブラリのみで動作)."""
from .store import DocChunk, DocumentStore
from .textnorm import content_tokens, normalize, tokenize
from .ingest import (
    ingest_markdown, ingest_markdown_file, ingest_pdf_file, ingest_dir, resolve_version,
)
from .retriever import Retriever, RetrievalHit, QueryAnalysis
from .agent import (
    QAAgent, Answer, Citation, REFUSAL, REFUSAL_PARTIAL,
    DEFAULT_MIN_SCORE, DEFAULT_MAX_OOS_RATIO,
)
from .approval import (
    ApprovalStore, ApprovalRequest, ApprovalError, detect_approval_intent,
    classify_intent, IntentResult, referenced_articles, VALID_STATUSES,
)
from .audit import AuditLog, AuditEntry
from .integrations import SlackNotifier, NotifyResult
from .policy import (
    ApprovalPolicy, ApprovalRoute, extract_amount, extract_amounts, AmountExtraction,
)
from .session import SessionStore, Session, Turn
from .staleness import (
    RegulationRegistry, RegulationVersion, VersionDiff, StaleCitation, check_answer_staleness,
)

__version__ = "1.1.0"

__all__ = [
    "DocChunk", "DocumentStore",
    "content_tokens", "normalize", "tokenize",
    "ingest_markdown", "ingest_markdown_file", "ingest_pdf_file", "ingest_dir",
    "resolve_version",
    "Retriever", "RetrievalHit", "QueryAnalysis",
    "QAAgent", "Answer", "Citation", "REFUSAL", "REFUSAL_PARTIAL",
    "DEFAULT_MIN_SCORE", "DEFAULT_MAX_OOS_RATIO",
    "ApprovalStore", "ApprovalRequest", "ApprovalError", "detect_approval_intent",
    "classify_intent", "IntentResult", "referenced_articles", "VALID_STATUSES",
    "AuditLog", "AuditEntry",
    "SlackNotifier", "NotifyResult",
    "ApprovalPolicy", "ApprovalRoute", "extract_amount", "extract_amounts",
    "AmountExtraction",
    "SessionStore", "Session", "Turn",
    "RegulationRegistry", "RegulationVersion", "VersionDiff", "StaleCitation",
    "check_answer_staleness",
    "__version__",
]
