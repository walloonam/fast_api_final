from pydantic import BaseModel
from typing import Dict, Optional

class Request(BaseModel):
    region: str
    access_key: str
    secret_access_key: str

class Response(BaseModel):
    region: str
    access_key: str
    secret_access_key: str

class EC2Instance(BaseModel):
    instance_id: str
    instance_type: str
    instance_name: str
    instance_engine: str
    state: str
    private_ip_address: str
    public_ip_address: str
    metrics: Dict[str, Optional[float]]
    reco: Optional[Dict[str, str]] = None



class RDSInstance(BaseModel):
    db_instance_identifier: str
    db_instance_class: str
    engine: str
    db_instance_status: str
    master_username: str
    endpoint: Dict[str, str]
    allocated_storage: int
    metrics: Dict[str, Optional[float]]
    reco: Optional[Dict[str, str]] = None



class Access(BaseModel):
    access_key_id: str
    secret_access_key: str
    region_name: str