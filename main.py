import asyncio
from fastapi.responses import JSONResponse

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from models import Request, Response, Access
from services import get_ec2_metric_statistics_async, get_rds_metric_statistics_async
import uvicorn

app = FastAPI()

@app.post("/api/metrics/", response_model_exclude_unset=True)
async def get_metrics(access: Access):
    ec2_metrics_task = get_ec2_metric_statistics_async(access.access_key_id, access.secret_access_key, access.region_name)
    rds_metrics_task = get_rds_metric_statistics_async(access.access_key_id, access.secret_access_key, access.region_name)

    ec2_metrics, rds_metrics = await asyncio.gather(ec2_metrics_task, rds_metrics_task)

    return {
        "ec2_metrics": ec2_metrics,
        "rds_metrics": rds_metrics
    }

@app.post("/api/endpoint", response_model=Response, responses={
    422: {"description": "Validation Error", "content": {"application/json": {"example": {"detail": "Validation Error: region field is required"}}}},
    400: {"description": "Bad Request", "content": {"application/json": {"example": {"detail": "Bad Request: Missing required fields"}}}}
})
async def process_request(request: Request):
    try:
        request_dict = request.dict()
        Request(**request_dict)
    except ValidationError as e:    
        raise HTTPException(status_code=422, detail=str(e))

    if not request.region or not request.access_key or not request.secret_access_key:
        raise HTTPException(status_code=400, detail="Bad Request: Missing required fields")
    
    return Response(region=request.region, access_key=request.access_key, secret_access_key=request.secret_access_key)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
