from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from app.core.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="other")  # nda | msa | employment | ... (heuristic)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)  # queued|processing|ready|failed
    stage: Mapped[str] = mapped_column(String(30), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    entity_count: Mapped[int] = mapped_column(Integer, default=0)
    suspicious_chunks: Mapped[int] = mapped_column(Integer, default=0)
    est_tokens: Mapped[int] = mapped_column(Integer, default=0)
    key_facts: Mapped[dict] = mapped_column(JSON, default=dict)
    risks: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan", order_by="Chunk.idx")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(200), default="")
    page: Mapped[int] = mapped_column(Integer, default=1)
    text: Mapped[str] = mapped_column(Text)
    suspicious: Mapped[bool] = mapped_column(default=False)   # contains instruction-like text (prompt-injection guard)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # float32 vector, rebuilt into FAISS at startup

    document: Mapped[Document] = relationship(back_populates="chunks")


class Entity(Base):
    """A node in the knowledge graph, merged across documents by (normalized name, type)."""

    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(30), index=True)
    description: Mapped[str] = mapped_column(Text, default="")


class Mention(Base):
    __tablename__ = "mentions"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    chunk_id: Mapped[int] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"), index=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)


class Relation(Base):
    __tablename__ = "relations"

    id: Mapped[int] = mapped_column(primary_key=True)
    src_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    dst_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    chunk_id: Mapped[int] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"), index=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Feedback(Base):
    """Thumbs up/down on an assistant answer. Exportable as an evaluation dataset."""
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True, unique=True)
    rating: Mapped[int] = mapped_column(Integer)          # +1 or -1
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


_url = get_settings().database_url
engine = create_engine(_url, connect_args={"check_same_thread": False} if _url.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        yield db


def est_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token for English). Used consistently so comparisons are fair."""
    return max(1, len(text) // 4)


def ensure_schema() -> None:
    """Add columns introduced after a database was first created (no Alembic in this app yet).

    create_all() only creates missing *tables*, so an older database would otherwise crash on the new
    columns. Each ALTER is idempotent: it only runs when the column is absent.
    """
    from sqlalchemy import inspect, text

    additions = {
        "documents": {"owner_id": "INTEGER", "content_hash": "VARCHAR(64)", "file_path": "VARCHAR(500)", "suspicious_chunks": "INTEGER DEFAULT 0"},
        "chunks": {"suspicious": "BOOLEAN DEFAULT 0"},
        "conversations": {"owner_id": "INTEGER"},
    }
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in additions.items():
            if not insp.has_table(table):
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for col, ddl in cols.items():
                if col not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
