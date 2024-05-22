from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "mysql+aiomysql://admin:test1234@mydb12.clyw8ymiu34j.ap-northeast-1.rds.amazonaws.com:3306/myDB"

# 비동기 엔진 생성
async_engine = create_async_engine(DATABASE_URL, echo=True)

# 비동기 세션 클래스 생성
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=async_engine, class_=AsyncSession)
async_session = SessionLocal()
