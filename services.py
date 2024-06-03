
import asyncio
import boto3
import botocore.exceptions
from datetime import datetime, timedelta
from typing import List
from models import EC2Instance, RDSInstance
from sqlalchemy.orm.exc import NoResultFound
from fastapi import HTTPException
from sqlalchemy import text
from database import async_engine
from sqlalchemy.ext.asyncio import AsyncSession

async def get_ec2_metric_statistics_async(access_key_id: str, secret_access_key: str, region_name: str) -> List[EC2Instance]:
    try:
        session = boto3.Session(
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region_name
        )
        
        ec2_client = session.client('ec2')
        cloudwatch_client = session.client('cloudwatch')

        # 자격 증명을 유효성 검사하기 위해 간단한 EC2 호출 수행
        ec2_client.describe_instances()

        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=7)

        instances = ec2_client.describe_instances()

        ec2_info_with_metrics = []

        for reservation in instances['Reservations']:
            for instance in reservation['Instances']:
                if instance['State']['Name'] != 'running':
                    continue
                instance_id = instance['InstanceId']
                instance_name = next((tag['Value'] for tag in instance.get('Tags', []) if tag['Key'] == 'Name'), "")
                instance_info = EC2Instance(
                    instance_id=instance_id,
                    instance_type=instance['InstanceType'],
                    instance_name=instance_name,
                    instance_engine=enginecheck(instance.get('PlatformDetails', 'Unknown')),
                    state=instance['State']['Name'],
                    private_ip_address=instance.get('PrivateIpAddress', 'N/A'),
                    public_ip_address=instance.get('PublicIpAddress', 'N/A'),
                    metrics={}
                )

                response = await asyncio.get_event_loop().run_in_executor(None, 
                    lambda: cloudwatch_client.get_metric_statistics(
                        Namespace='AWS/EC2',
                        MetricName='CPUUtilization',
                        Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
                        StartTime=start_time,
                        EndTime=end_time,
                        Period=3600,
                        Statistics=['Minimum', 'Maximum', 'Average']
                    )
                )

                if 'Datapoints' not in response or not response['Datapoints']:
                    instance_info.metrics['Minimum'] = None
                    instance_info.metrics['Maximum'] = None
                    instance_info.metrics['Average'] = None
                else:
                    min_value = min([datapoint['Minimum'] for datapoint in response['Datapoints']])
                    max_value = max([datapoint['Maximum'] for datapoint in response['Datapoints']])
                    avg_value = sum([datapoint['Average'] for datapoint in response['Datapoints']]) / len(response['Datapoints'])

                    instance_info.metrics['Minimum'] = min_value
                    instance_info.metrics['Maximum'] = max_value
                    instance_info.metrics['Average'] = avg_value

                    reco_info = await reco_instance_ec2(instance['InstanceType'],instance_info.instance_engine, max_value)
                    instance_info.reco = reco_info

                ec2_info_with_metrics.append(instance_info)

        return ec2_info_with_metrics
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == 'AuthFailure':
            raise HTTPException(status_code=401, detail="유효하지 않은 AWS 자격 증명입니다. 액세스 키와 비밀 액세스 키를 확인하세요.")
        elif e.response['Error']['Code'] == 'SignatureDoesNotMatch':
            raise HTTPException(status_code=403, detail="요청 서명이 유효하지 않습니다. 시스템 시간 동기화를 확인하세요.")
        else:
            raise HTTPException(status_code=500, detail=f"알 수 없는 오류가 발생했습니다: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"예상치 못한 오류가 발생했습니다: {str(e)}")

    


async def get_rds_metric_statistics_async(access_key_id: str, secret_access_key: str, region_name: str) -> List[RDSInstance]:
    session = boto3.Session(
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region_name
    )
    cloudwatch = session.client('cloudwatch')
    rds_client = session.client('rds')

    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=7)

    rds_info_with_metrics = []

    next_token = None
    while True:
        if next_token:
            instances = rds_client.describe_db_instances(NextToken=next_token)
        else:
            instances = rds_client.describe_db_instances()

        for instance in instances['DBInstances']:
            db_instance_identifier = instance['DBInstanceIdentifier']
            endpoint = instance['Endpoint']
            endpoint['Port'] = str(endpoint['Port'])
            instance_info = RDSInstance(
                db_instance_identifier=db_instance_identifier,
                db_instance_class=instance['DBInstanceClass'],
                engine=instance['Engine'],
                db_instance_status=instance['DBInstanceStatus'],
                master_username=instance['MasterUsername'],
                endpoint=endpoint,
                allocated_storage=instance['AllocatedStorage'],
                metrics={}
            )

            # metrics = ['CPUUtilization', 'DatabaseConnections', 'FreeStorageSpace']
            metrics = ['CPUUtilization']
            for metric_name in metrics:
                response = await asyncio.get_event_loop().run_in_executor(None, 
                    lambda: cloudwatch.get_metric_statistics(
                        Namespace='AWS/RDS',
                        MetricName=metric_name,
                        Dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': db_instance_identifier}],
                        StartTime=start_time,
                        EndTime=end_time,
                        Period=3600,
                        Statistics=['Minimum', 'Maximum', 'Average']
                    )
                )

                if 'Datapoints' not in response or not response['Datapoints']:
                    instance_info.metrics[metric_name] = {
                        'Minimum': None,
                        'Maximum': None,
                        'Average': None
                    }
                else:
                    min_value = min([datapoint['Minimum'] for datapoint in response['Datapoints']])
                    max_value = max([datapoint['Maximum'] for datapoint in response['Datapoints']])
                    avg_value = sum([datapoint['Average'] for datapoint in response['Datapoints']]) / len(response['Datapoints'])

                    instance_info.metrics[metric_name] = {
                        'Minimum': min_value,
                        'Maximum': max_value,
                        'Average': avg_value
                    }
                print(instance_info.metrics)
                reco_info = await reco_instance_rds(instance['DBInstanceClass'], instance_info.engine, instance_info.metrics['CPUUtilization']['Maximum'])
                instance_info.reco = reco_info

            rds_info_with_metrics.append(instance_info)

        next_token = instances.get('NextToken')
        if not next_token:
            break

    return rds_info_with_metrics


async def reco_instance_ec2(instance_type: str, engine:str, maximum: float):
    async with AsyncSession(async_engine) as session:
        async with session.begin():
            try:
                # 주어진 instance_type의 가격을 조회
                result = await session.execute(text("""
                    SELECT ec2_vcpu, ec2_memory, ec2_price
                    FROM ec2_ondemand_pricing
                    WHERE ec2_instance_type = :instance_type
                    AND ec2_os_engine = :engine 
                    AND `description` = "UNKNOWN"
                    ORDER BY ec2_price ASC
                """), {"instance_type": instance_type,"engine": engine})
                row = result.fetchone()
                print(row)

                if not row:
                    raise HTTPException(status_code=404, detail=f"No matching instance type found for '{instance_type}'")

                ec2_vcpu, ec2_memory, ec2_price = row

                # instance_type의 . 이전 부분을 추출
                like_pattern = instance_type.split('.')[0] + '.%'
                print(ec2_price)
                # 가격이 주어진 instance_type보다 낮은 . 이전 부분이 같은 인스턴스 유형들을 조회
                result = await session.execute(text("""
                    SELECT DISTINCT ec2_instance_type, ec2_vcpu, ec2_memory, ec2_price, ec2_os_engine
                    FROM ec2_ondemand_pricing
                    WHERE ec2_instance_type LIKE :like_pattern
                    AND ec2_price > 0  
                    AND ec2_os_engine = :engine  
                    AND `description` = "UNKNOWN"
                    AND ec2_price < :ec2_price
                    ORDER BY ec2_price ASC
                """), {"like_pattern": like_pattern, "ec2_price": ec2_price, "engine": engine})
                lower_priced_instances = result.fetchall()
                
                reco = []

                for reco_instance in lower_priced_instances:
                    reco_cpu = int(ec2_vcpu) / int(reco_instance.ec2_vcpu) / 2
                    reco_instance_memory_numeric = float(reco_instance.ec2_memory.replace("GiB", "").strip())
                    ec2_memory_numeric = float(ec2_memory.replace("GiB", "").strip())
                    reco_memory = ec2_memory_numeric / reco_instance_memory_numeric / 2  
                    expected_max= maximum * (1.58 **reco_cpu)*(1.22** reco_memory)         
                    if expected_max < 70:
                        reco.append({
                            "instance_type": reco_instance.ec2_instance_type,
                            "ec2_os_engine" : reco_instance.ec2_os_engine,
                            "price": float(reco_instance.ec2_price),
                            "expected_max" : float(expected_max)
                        })

                return reco
                                
            except NoResultFound:
                raise HTTPException(status_code=404, detail=f"No matching instance type found for '{instance_type}'")


async def reco_instance_rds(instance_type: str, engine:str, maximum:float):
    async with AsyncSession(async_engine) as session:
        async with session.begin():
            try:
                # 쿼리 실행
                result = await session.execute(text("""
                    SELECT vcpu, memory, price
                    FROM rds_pricing
                    WHERE instance_type = :instance_type
                    AND ENGINE = :engine
                    AND deploymentOption = "Single-AZ"
                """), {"instance_type": instance_type, "engine": engine})
                row = result.fetchone()

                if not row:
                    raise HTTPException(status_code=404, detail=f"No matching instance type found for '{instance_type}'")
                vcpu, memory, price = row

                # 첫 번째 마침표의 인덱스를 찾습니다.
                first_dot_index = instance_type.find('.')
                if first_dot_index == -1:
                    raise ValueError("첫 번째 마침표를 찾을 수 없습니다.")
                
                # 두 번째 마침표의 인덱스를 찾습니다.
                second_dot_index = instance_type.find('.', first_dot_index + 1)
                if second_dot_index == -1:
                    raise ValueError("두 번째 마침표를 찾을 수 없습니다.")
                
                # like_pattern을 생성합니다.
                like_pattern = instance_type[:second_dot_index] + '.%'
                print(like_pattern)
                print("hi")
                # 가격이 주어진 instance_type보다 낮은 . 이전 부분이 같은 인스턴스 유형들을 조회
                result = await session.execute(text("""
                    SELECT DISTINCT instance_type, vcpu, memory, price, ENGINE
                    FROM rds_pricing
                    WHERE instance_type LIKE :like_pattern
                    AND price > 0  
                    AND ENGINE = :engine
                    AND deploymentOption = "Single-AZ"
                    AND price < :price
                    ORDER BY price ASC
                """), {"like_pattern": like_pattern, "price": price, "engine": engine})
                lower_priced_instances = result.fetchall()
                
                reco = []

                for reco_instance in lower_priced_instances:
                    reco_cpu = int(vcpu) / int(reco_instance.vcpu) / 2
                    reco_instance_memory_numeric = float(reco_instance.memory.replace("GiB", "").strip())
                    memory_numeric = float(memory.replace("GiB", "").strip())
                    reco_memory = memory_numeric / reco_instance_memory_numeric / 2 
                    expected_max = maximum * (1.58 **reco_cpu)*(1.22** reco_memory)
                    if expected_max < 70:
                        reco.append({
                            "instance_type": reco_instance.instance_type,
                            "rds_engine" : reco_instance.ENGINE,
                            "price": float(reco_instance.price),
                            "expected_max" : float(expected_max)
                        })

                return reco
            except NoResultFound:
                raise HTTPException(status_code=404, detail=f"No matching instance type found for '{instance_type}'")
            


def enginecheck(engine: str):
    if engine == "Linux/UNIX":
        return "Linux"
    elif engine == "Windows":
        return "Windows"
    elif engine == "SUSE Linux":
        return "SUSE"
    elif engine == "Red Hat Enterprise Linux":
        return "RHEL"