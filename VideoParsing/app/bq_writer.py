import datetime
import logging

from google.cloud import bigquery

from app.config import Config

logger = logging.getLogger(__name__)

SCHEMA = [
    bigquery.SchemaField("video_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("segment_index", "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("gcs_uri", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("description", "STRING"),
    bigquery.SchemaField("objects", "STRING", mode="REPEATED"),
    bigquery.SchemaField("scenes", "RECORD", mode="REPEATED", fields=[
        bigquery.SchemaField("timestamp", "FLOAT"),
        bigquery.SchemaField("description", "STRING"),
    ]),
    bigquery.SchemaField("transcript", "STRING"),
    bigquery.SchemaField("key_moments", "RECORD", mode="REPEATED", fields=[
        bigquery.SchemaField("timestamp", "FLOAT"),
        bigquery.SchemaField("description", "STRING"),
    ]),
    bigquery.SchemaField("processed_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("duration_sec", "FLOAT"),
]


def _get_client() -> bigquery.Client:
    return bigquery.Client(project=Config.PROJECT_ID)


def ensure_table_exists() -> None:
    client = _get_client()
    dataset_ref = bigquery.DatasetReference(Config.PROJECT_ID, Config.BQ_DATASET)

    try:
        client.get_dataset(dataset_ref)
    except Exception:
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = Config.REGION
        client.create_dataset(dataset)
        logger.info("Created dataset %s", Config.BQ_DATASET)

    table_ref = dataset_ref.table(Config.BQ_TABLE)
    try:
        client.get_table(table_ref)
    except Exception:
        table = bigquery.Table(table_ref, schema=SCHEMA)
        client.create_table(table)
        logger.info("Created table %s.%s", Config.BQ_DATASET, Config.BQ_TABLE)


def is_video_processed(video_id: str) -> bool:
    client = _get_client()
    table_id = f"{Config.PROJECT_ID}.{Config.BQ_DATASET}.{Config.BQ_TABLE}"
    query = f"SELECT 1 FROM `{table_id}` WHERE video_id = @video_id LIMIT 1"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("video_id", "STRING", video_id)]
    )
    try:
        results = client.query(query, job_config=job_config).result()
        return results.total_rows > 0
    except Exception:
        return False


def write_segment_metadata(
    video_id: str,
    segment_index: int,
    gcs_uri: str,
    metadata: dict,
    duration_sec: float,
) -> None:
    client = _get_client()
    table_id = f"{Config.PROJECT_ID}.{Config.BQ_DATASET}.{Config.BQ_TABLE}"

    row = {
        "video_id": video_id,
        "segment_index": segment_index,
        "gcs_uri": gcs_uri,
        "description": metadata.get("description", ""),
        "objects": metadata.get("objects", []),
        "scenes": [
            {"timestamp": s.get("timestamp", 0.0), "description": s.get("description", "")}
            for s in metadata.get("scenes", [])
        ],
        "transcript": metadata.get("transcript", ""),
        "key_moments": [
            {"timestamp": m.get("timestamp", 0.0), "description": m.get("description", "")}
            for m in metadata.get("key_moments", [])
        ],
        "processed_at": datetime.datetime.utcnow().isoformat(),
        "duration_sec": duration_sec,
    }

    errors = client.insert_rows_json(table_id, [row])
    if errors:
        raise RuntimeError(f"BigQuery insert errors: {errors}")
    logger.info("Wrote metadata for %s segment %d", video_id, segment_index)
