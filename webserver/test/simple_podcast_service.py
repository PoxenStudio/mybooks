import os
import uuid
import shutil
import mimetypes
import email.utils
from datetime import datetime, timezone
from typing import List
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Float
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from pydantic import BaseModel
from feedgen.feed import FeedGenerator
import mutagen

# ================= 配置 =================
DATABASE_URL = "sqlite:///./podcast.db"
UPLOAD_DIR = "./uploads"
HOST = "http://localhost:8000"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ================= 数据库 =================
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Episode(Base):
    __tablename__ = "episodes"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    filename = Column(String(255), unique=True, nullable=False)
    audio_url = Column(String(500), nullable=False)
    pub_date = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    duration = Column(Float, default=0.0)  # 秒
    file_size = Column(Integer, default=0)
    mime_type = Column(String(50), default="audio/mpeg")

Base.metadata.create_all(bind=engine)

def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ================= Pydantic 模型 =================
class EpisodeResponse(BaseModel):
    id: int
    title: str
    description: str | None
    audio_url: str
    pub_date: datetime
    duration: float
    class Config:
        from_attributes = True

# ================= 工具函数 =================
def get_audio_duration(filepath: str) -> float:
    try:
        audio = mutagen.File(filepath)
        return float(audio.info.length) if audio and audio.info else 0.0
    except Exception:
        return 0.0

# ================= 应用 =================
app = FastAPI(title="Python Podcast Service", version="1.0")

@app.post("/episodes/", response_model=EpisodeResponse)
async def upload_episode(
    title: str,
    description: str = "",
    file: UploadFile = File(...)
):
    # 基础校验
    allowed_ext = {".mp3", ".m4a", ".wav", ".ogg"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_ext:
        raise HTTPException(400, f"仅支持 {', '.join(allowed_ext)} 格式")

    # 保存文件
    unique_name = f"{uuid.uuid4()}{ext}"
    filepath = os.path.join(UPLOAD_DIR, unique_name)
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # 提取元数据
    file_size = os.path.getsize(filepath)
    duration = get_audio_duration(filepath)
    mime_type, _ = mimetypes.guess_type(filepath)
    mime_type = mime_type or "audio/mpeg"

    # 入库
    db = SessionLocal()
    try:
        episode = Episode(
            title=title,
            description=description,
            filename=unique_name,
            audio_url=f"{HOST}/audio/{unique_name}",
            pub_date=datetime.now(timezone.utc),
            duration=duration,
            file_size=file_size,
            mime_type=mime_type
        )
        db.add(episode)
        db.commit()
        db.refresh(episode)
        return episode
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()

@app.get("/episodes/", response_model=List[EpisodeResponse])
def list_episodes(db: Session = Depends(get_db)):
    return db.query(Episode).order_by(Episode.pub_date.desc()).all()

@app.get("/feed.xml")
def generate_rss(db: Session = Depends(get_db)):
    episodes = db.query(Episode).order_by(Episode.pub_date.desc()).all()

    fg = FeedGenerator()
    fg.id(f"{HOST}/podcast")
    fg.title("我的 Python 播客")
    fg.author({"name": "作者", "email": "author@example.com"})
    fg.link(href=HOST, rel="alternate")
    fg.description("用 Python 搭建的播客服务示例")
    fg.language("zh-CN")
    fg.itunes.image(f"{HOST}/cover.jpg")
    fg.itunes.category("Technology", "Software How-To")
    fg.itunes.explicit("no")

    for ep in episodes:
        fe = fg.add_entry()
        fe.id(ep.audio_url)
        fe.title(ep.title)
        fe.description(ep.description)
        fe.link(href=ep.audio_url)
        fe.pubDate(email.utils.format_datetime(ep.pub_date))
        fe.enclosure(
            ep.audio_url,
            str(ep.file_size),
            ep.mime_type
        )
        fe.itunes.duration(str(int(ep.duration)))
        fe.itunes.explicit("no")

    return Response(content=fg.rss_str(pretty=True), media_type="application/rss+xml; charset=utf-8")

@app.get("/audio/{filename}")
def serve_audio(filename: str):
    filepath = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(404, "音频文件不存在")
    return FileResponse(filepath, media_type="audio/mpeg", filename=filename)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
