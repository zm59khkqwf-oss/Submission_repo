# vertex_pipeline.py: defines a dry-run that pulls cleaned vitals from BigQuery, trains a simple sklearn model (Logistic regression), registers it in the Model Registry, and deploys it to a Vertex Endpoint.
# # DRY RUN ONLY 

from kfp import dsl
from kfp.dsl import Dataset, Output, Model, Input
from kfp import compiler
# from google.cloud import aiplatform # not needed for dry run



# Step 0 — Define identifiers/paths & Initialize Vertex AI SDK
Project_id = "arched-media-390414"
region = "europe-west4"   # pick one EU Vertex region (required; can't be just "EU")

Bucket_name = "bucket_name" # placeholder (dry-run): requires billing 
pipeline_root = f"gs://{Bucket_name}/pipelines/septic_shock_risk"  # tells Vertex where to write artifacts (in GCS)

# aiplatform.init(project=Project_id, location=region) ;  Note: dry run 

# Step 1 — BigQuery → Dataset artifact (extract cleaned vitals)
BQ_SOURCE_TABLE = "arched-media-390414.icu_analytics.vitals_clean" # cleaned BQ table from ingest.py output (loaded in BigQuery)


@dsl.component(
    base_image="python:3.10",
    packages_to_install=["pandas", "numpy", "google-cloud-bigquery", "db-dtypes"] 
)
def extract_from_bq(
    bq_table: str,
    output_dataset: Output[Dataset],
):
    """
    Exports BigQuery table to a CSV file in the component's output path.
    In real runs, you'd export to GCS; for dry-run, this shows correct structure.
    """
    import pandas as pd
    import numpy as np
    from google.cloud import bigquery

    client = bigquery.Client() 

    # Read table into a dataframe 
    df = client.query(f"SELECT * FROM `{bq_table}`").to_dataframe() 
    df.to_csv(output_dataset.path, index=False) # Write to the output path


# Step 2 — Create synthetic target variable (for this assesement) + Train a simple model (logistic regression).
@dsl.component(
    base_image="python:3.10",
    packages_to_install=["pandas", "numpy", "scikit-learn", "joblib"]  
)
def train_model(
    input_dataset: Input[Dataset],
    output_model: Output[Model],
):
    import json
    import joblib
    import numpy as np
    import pandas as pd
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split

    df = pd.read_csv(input_dataset.path) # read csv from previous step

    # target value
    p = 0.12  # 12% positives to simulate septic shock risk (synthetic column)
    rng = np.random.default_rng(27)  
    df["risk"] = rng.binomial(1, p, size=len(df)).astype(int) # 0/1 label synthetic 

    feature_cols = ["heart_rate", "body_temperature", "spO2", "battery_level"] # features to use 

    df_train = df[feature_cols + ["risk"]].dropna() # could do more cleaning here, dropna is just for demo. 

    X = df_train[feature_cols]
    y = df_train["risk"]

    # train/test split 
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=27) # simple

    model = LogisticRegression(max_iter=1000, random_state=27) 
    model.fit(X_train, y_train)  # train 

    # Save artifacts into the model directory that Vertex expects
    model_path = f"{output_model.path}/trained_model.joblib"
    meta_path = f"{output_model.path}/feature_cols.json"

    joblib.dump(model, model_path)
    with open(meta_path, "w") as f:
        json.dump({"feature_cols": feature_cols}, f)



# Step 3 — Register the trained model in Vertex Model Registry (for deployment and versioning)
@dsl.component(
    base_image="python:3.10",
    packages_to_install=["google-cloud-aiplatform"] 
)
def upload_model_to_registry(
    trained_model: Input[Model],   # <-- output from 
    project: str,
    location: str,
    display_name: str = "septic-shock-risk-sklearn",
) -> str:

    from google.cloud import aiplatform

    # (1) Init inside the component 
    aiplatform.init(project=project, location=location)

    # (2) This is the location of the model artifacts.
    artifact_uri = trained_model.uri   # In a real run, trained_model.uri will resolve to a GCS artifact directory under pipeline_root

    # (3) Create a versioned Model in Vertex Model Registry
    vertex_model = aiplatform.Model.upload(
        display_name=display_name,
        artifact_uri=artifact_uri,
        serving_container_image_uri="europe-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-5:latest", # Prebuilt sklearn serving container (EU registry host)
    )

    # (4) Return the Model ID for later deployment (Step 5)
    return vertex_model.resource_name



# Step 4 — Deploy the registered model to a Vertex Endpoint 
@dsl.component(
    base_image="python:3.10",
    packages_to_install=["google-cloud-aiplatform"]
)
def create_endpoint_and_deploy(
    model_resource_name: str,
    project: str,
    location: str,
    endpoint_display_name: str = "septic-shock-risk-endpoint",
    machine_type: str = "n1-standard-2",
) -> str:
    from google.cloud import aiplatform

    aiplatform.init(project=project, location=location)

    # 1) Create endpoint (a stable serving address)
    endpoint = aiplatform.Endpoint.create(display_name=endpoint_display_name)

    # 2) Load the registered model by ID
    model = aiplatform.Model(model_resource_name)

    # 3) Deploy model to endpoint (this provisions compute + starts serving)
    endpoint.deploy(
        model=model,
        machine_type=machine_type,
        traffic_percentage=100, 
    )

    return endpoint.resource_name


# Step 5 - Pipeline 
@dsl.pipeline(
    name="septic-shock-risk-pipeline",
    pipeline_root=pipeline_root
)
def septic_shock_pipeline(bq_table: str = BQ_SOURCE_TABLE):
    # Ingest from BQ -> Train -> Register Model -> deploy to endpoint (structure)

    extract_task = extract_from_bq(bq_table=bq_table)

    train_task = train_model(
        input_dataset=extract_task.outputs["output_dataset"]
    )

    upload_task = upload_model_to_registry(
        trained_model=train_task.outputs["output_model"],
        project=Project_id,
        location=region,
        display_name="septic-shock-risk-sklearn",
    )

    deploy_task = create_endpoint_and_deploy(
        model_resource_name=upload_task.output,
        project=Project_id,
        location=region,
        endpoint_display_name="septic-shock-risk-endpoint",
        machine_type="n1-standard-2",
    )


if __name__ == "__main__":
    compiler.Compiler().compile(
        pipeline_func=septic_shock_pipeline,
        package_path="septic_shock_pipeline.json",
    )






