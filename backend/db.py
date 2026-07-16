"""
SQLite database layer via SQLAlchemy (no Alembic).
Tables are created automatically on first startup.
"""
import os
from sqlalchemy import (
    create_engine, Column, String, Integer, Float, Text,
    ForeignKey, DateTime, JSON
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker, relationship
from sqlalchemy.sql import func

DB_PATH = os.getenv("DB_PATH", "storage/constructos.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"
    id          = Column(String, primary_key=True)
    name        = Column(String, nullable=False)
    description = Column(Text, default="")
    created_at  = Column(DateTime, server_default=func.now())
    documents   = relationship("ProjectDocument", back_populates="project", cascade="all, delete-orphan")
    facts       = relationship("Fact", back_populates="project", cascade="all, delete-orphan")
    conflicts   = relationship("Conflict", back_populates="project", cascade="all, delete-orphan")
    rfis        = relationship("RFI", back_populates="project", cascade="all, delete-orphan")


class ProjectDocument(Base):
    __tablename__ = "project_documents"
    id           = Column(String, primary_key=True)          # same as chroma doc_id
    project_id   = Column(String, ForeignKey("projects.id"), nullable=False)
    filename     = Column(String, nullable=False)
    document_type = Column(String, default="other")          # blueprint|specification|boq|method_statement|other
    page_count   = Column(Integer, default=0)
    chunk_count  = Column(Integer, default=0)
    added_at     = Column(DateTime, server_default=func.now())
    updated_at   = Column(DateTime, server_default=func.now(), onupdate=func.now())
    status       = Column(String, default="pending")
    status_detail = Column(String, nullable=True)
    project      = relationship("Project", back_populates="documents")
    facts        = relationship("Fact", back_populates="document", cascade="all, delete-orphan")


class Fact(Base):
    __tablename__ = "facts"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    project_id   = Column(String, ForeignKey("projects.id"), nullable=False)
    document_id  = Column(String, ForeignKey("project_documents.id"), nullable=False)
    category     = Column(String)   # structural|architectural|mep
    field        = Column(String)   # slab_thickness|concrete_grade|…
    value        = Column(String)   # "200 mm"
    unit         = Column(String, default="")
    page         = Column(Integer, default=0)
    sheet        = Column(String, default="")
    section      = Column(String, default="")
    quote        = Column(Text, default="")
    project      = relationship("Project", back_populates="facts")
    document     = relationship("ProjectDocument", back_populates="facts")


class Conflict(Base):
    __tablename__ = "conflicts"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    project_id      = Column(String, ForeignKey("projects.id"), nullable=False)
    field           = Column(String)
    blueprint_value = Column(String)
    spec_value      = Column(String)
    blueprint_doc_id = Column(String)
    spec_doc_id     = Column(String)
    blueprint_page  = Column(Integer, default=0)
    spec_page       = Column(Integer, default=0)
    blueprint_sheet = Column(String, default="")
    spec_section    = Column(String, default="")
    status          = Column(String, default="conflict")   # conflict|warning|ok
    severity        = Column(String, default="medium")
    created_at      = Column(DateTime, server_default=func.now())
    project         = relationship("Project", back_populates="conflicts")


class RFI(Base):
    __tablename__ = "rfis"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    project_id   = Column(String, ForeignKey("projects.id"), nullable=False)
    conflict_id  = Column(Integer, ForeignKey("conflicts.id"), nullable=True)
    number       = Column(String)   # "RFI-001"
    subject      = Column(String)
    body         = Column(Text)
    priority     = Column(String, default="medium")
    status       = Column(String, default="open")
    references_json = Column(JSON, nullable=True, default=None)  # persisted Reference list
    created_at   = Column(DateTime, server_default=func.now())
    project      = relationship("Project", back_populates="rfis")

def _auto_migrate():
    """
    Lightweight migration: add any columns defined in ORM models but missing
    from the existing SQLite tables.  Avoids a full Alembic dependency for
    simple ALTER TABLE ADD COLUMN operations.
    """
    from sqlalchemy import inspect as sa_inspect, text
    inspector = sa_inspect(engine)
    for table_name, table_obj in Base.metadata.tables.items():
        if table_name not in inspector.get_table_names():
            continue  # table doesn't exist yet — create_all handles it
        existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
        for col in table_obj.columns:
            if col.name not in existing_cols:
                col_type = col.type.compile(engine.dialect)
                default_clause = ""
                if col.default is not None:
                    default_clause = f" DEFAULT {col.default.arg!r}"
                elif col.nullable:
                    default_clause = " DEFAULT NULL"
                stmt = f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}{default_clause}"
                with engine.begin() as conn:
                    conn.execute(text(stmt))

def init_db():
    Base.metadata.create_all(bind=engine)
    _auto_migrate()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
