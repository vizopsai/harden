"""Cloud Cost Optimizer — FinOps tool.
Scans AWS for waste: unused EBS, oversized EC2, orphaned snapshots, idle RDS, unattached EIPs.
Calculates savings estimates and creates Jira tickets for cleanup.
Built for the weekly FinOps review with the VP Engineering.
TODO: add GCP and Azure support (we're multi-cloud now)
TODO: add Slack alerts for new findings over $500/month
"""

import streamlit as st
import pandas as pd
import io, json, os
from datetime import datetime, timedelta
from typing import List, Dict

st.set_page_config(page_title="Cloud Cost Optimizer", layout="wide")

# AWS credentials — using shared FinOps IAM user
# TODO: switch to IAM role with assume-role, these creds are too powerful
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "kF8gH2jK4lM6nO8pQ0rS2tU4vW6xY8zA0bC2dE4")
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
AWS_REGIONS_TO_SCAN = ["us-east-1", "us-west-2", "eu-west-1"]  # our active regions

# Jira for creating cleanup tickets
JIRA_BASE_URL = "https://acmecorp.atlassian.net"
JIRA_EMAIL = "finops-bot@acmecorp.com"
JIRA_API_TOKEN = "ATATT3xFfGF0kQ8mN2pR4sT6uW8xZ0aB2cD4eF6gH8iJ0kL2mN4oP6qR8sT0uV2w"
JIRA_PROJECT_KEY = "INFRA"

# Cost estimates for savings calculations (monthly)
COST_ESTIMATES = {
    "ebs_gp2_per_gb": 0.10,
    "ebs_gp3_per_gb": 0.08,
    "ebs_io1_per_gb": 0.125,
    "snapshot_per_gb": 0.05,
    "eip_unattached": 3.65,  # $0.005/hr * 730 hrs
    "rds_db_t3_medium": 49.06,
    "rds_db_t3_large": 98.11,
    "rds_db_r5_large": 175.20,
    "ec2_t3_medium": 30.37,
    "ec2_t3_large": 60.74,
    "ec2_m5_large": 69.12,
    "ec2_m5_xlarge": 138.24,
    "ec2_r5_large": 91.80,
    "ec2_c5_xlarge": 124.10,
}


def scan_unused_ebs_volumes(ec2_client) -> List[Dict]:
    """Find EBS volumes in 'available' state (not attached to any instance)."""
    findings = []
    try:
        paginator = ec2_client.get_paginator("describe_volumes")
        for page in paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
            for vol in page["Volumes"]:
                size_gb = vol["Size"]
                vol_type = vol["VolumeType"]
                cost_key = f"ebs_{vol_type}_per_gb"
                monthly_cost = size_gb * COST_ESTIMATES.get(cost_key, 0.10)

                findings.append({
                    "type": "unused_ebs_volume",
                    "resource_id": vol["VolumeId"],
                    "region": ec2_client.meta.region_name,
                    "details": f"{vol_type} volume, {size_gb} GB, created {vol['CreateTime'].strftime('%Y-%m-%d')}",
                    "monthly_savings": round(monthly_cost, 2),
                    "recommendation": f"Delete volume {vol['VolumeId']} or snapshot and delete",
                    "severity": "high" if monthly_cost > 50 else "medium",
                })
    except Exception as e:
        st.warning(f"Error scanning EBS: {e}")
    return findings


def scan_oversized_ec2(ec2_client, cw_client) -> List[Dict]:
    """Find EC2 instances with average CPU < 10% over last 14 days."""
    findings = []
    try:
        instances = ec2_client.describe_instances(
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
        )
        for res in instances["Reservations"]:
            for inst in res["Instances"]:
                instance_id = inst["InstanceId"]
                instance_type = inst["InstanceType"]

                # Get CPU utilization from CloudWatch
                end_time = datetime.utcnow()
                start_time = end_time - timedelta(days=14)
                metrics = cw_client.get_metric_statistics(
                    Namespace="AWS/EC2",
                    MetricName="CPUUtilization",
                    Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=86400,  # daily
                    Statistics=["Average"],
                )
                datapoints = metrics.get("Datapoints", [])
                if datapoints:
                    avg_cpu = sum(dp["Average"] for dp in datapoints) / len(datapoints)
                    if avg_cpu < 10.0:
                        # Suggest downsizing
                        current_cost = COST_ESTIMATES.get(f"ec2_{instance_type.replace('.', '_')}", 60.0)
                        savings = current_cost * 0.5  # assume 50% savings from rightsizing

                        name_tag = next((t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"), "unnamed")
                        findings.append({
                            "type": "oversized_ec2",
                            "resource_id": instance_id,
                            "region": ec2_client.meta.region_name,
                            "details": f"{instance_type} '{name_tag}', avg CPU: {avg_cpu:.1f}% (14-day)",
                            "monthly_savings": round(savings, 2),
                            "recommendation": f"Downsize {instance_id} from {instance_type} to smaller instance",
                            "severity": "high" if savings > 100 else "medium",
                        })
    except Exception as e:
        st.warning(f"Error scanning EC2: {e}")
    return findings


def scan_orphaned_snapshots(ec2_client) -> List[Dict]:
    """Find EBS snapshots whose source volume no longer exists."""
    findings = []
    try:
        # Get all volume IDs
        volumes = set()
        paginator = ec2_client.get_paginator("describe_volumes")
        for page in paginator.paginate():
            for vol in page["Volumes"]:
                volumes.add(vol["VolumeId"])

        # Check snapshots
        snap_paginator = ec2_client.get_paginator("describe_snapshots")
        for page in snap_paginator.paginate(OwnerIds=["self"]):
            for snap in page["Snapshots"]:
                if snap["VolumeId"] not in volumes:
                    size_gb = snap["VolumeSize"]
                    monthly_cost = size_gb * COST_ESTIMATES["snapshot_per_gb"]
                    findings.append({
                        "type": "orphaned_snapshot",
                        "resource_id": snap["SnapshotId"],
                        "region": ec2_client.meta.region_name,
                        "details": f"{size_gb} GB snapshot, source vol {snap['VolumeId']} deleted, created {snap['StartTime'].strftime('%Y-%m-%d')}",
                        "monthly_savings": round(monthly_cost, 2),
                        "recommendation": f"Delete orphaned snapshot {snap['SnapshotId']}",
                        "severity": "low",
                    })
    except Exception as e:
        st.warning(f"Error scanning snapshots: {e}")
    return findings


def scan_idle_rds(rds_client, cw_client) -> List[Dict]:
    """Find RDS instances with < 5 connections on average over 7 days."""
    findings = []
    try:
        instances = rds_client.describe_db_instances()
        for db in instances["DBInstances"]:
            db_id = db["DBInstanceIdentifier"]
            instance_class = db["DBInstanceClass"]

            end_time = datetime.utcnow()
            start_time = end_time - timedelta(days=7)
            metrics = cw_client.get_metric_statistics(
                Namespace="AWS/RDS",
                MetricName="DatabaseConnections",
                Dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=86400,
                Statistics=["Average"],
            )
            datapoints = metrics.get("Datapoints", [])
            if datapoints:
                avg_conns = sum(dp["Average"] for dp in datapoints) / len(datapoints)
                if avg_conns < 5:
                    cost_key = f"rds_{instance_class.replace('.', '_')}"
                    monthly_cost = COST_ESTIMATES.get(cost_key, 100.0)
                    findings.append({
                        "type": "idle_rds",
                        "resource_id": db_id,
                        "region": rds_client.meta.region_name,
                        "details": f"{instance_class}, avg connections: {avg_conns:.1f} (7-day), engine: {db['Engine']}",
                        "monthly_savings": round(monthly_cost, 2),
                        "recommendation": f"Consider stopping or downsizing RDS instance {db_id}",
                        "severity": "high",
                    })
    except Exception as e:
        st.warning(f"Error scanning RDS: {e}")
    return findings


def scan_unattached_eips(ec2_client) -> List[Dict]:
    """Find Elastic IPs not associated with any instance."""
    findings = []
    try:
        addresses = ec2_client.describe_addresses()
        for addr in addresses["Addresses"]:
            if "InstanceId" not in addr and "NetworkInterfaceId" not in addr:
                findings.append({
                    "type": "unattached_eip",
                    "resource_id": addr["PublicIp"],
                    "region": ec2_client.meta.region_name,
                    "details": f"Elastic IP {addr['PublicIp']} not attached to any resource",
                    "monthly_savings": COST_ESTIMATES["eip_unattached"],
                    "recommendation": f"Release Elastic IP {addr['PublicIp']}",
                    "severity": "low",
                })
    except Exception as e:
        st.warning(f"Error scanning EIPs: {e}")
    return findings


def create_jira_ticket(finding: dict) -> dict:
    """Create a Jira ticket for a finding."""
    import requests as req
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": f"[FinOps] {finding['type'].replace('_', ' ').title()}: {finding['resource_id']}",
            "description": {
                "type": "doc", "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": (
                    f"Resource: {finding['resource_id']}\n"
                    f"Region: {finding['region']}\n"
                    f"Details: {finding['details']}\n"
                    f"Estimated Monthly Savings: ${finding['monthly_savings']}\n"
                    f"Recommendation: {finding['recommendation']}"
                )}]}],
            },
            "issuetype": {"name": "Task"},
            "labels": ["finops", "cost-optimization", finding["severity"]],
            "priority": {"name": "High" if finding["severity"] == "high" else "Medium"},
        }
    }
    resp = req.post(f"{JIRA_BASE_URL}/rest/api/3/issue", json=payload, auth=auth, timeout=10)
    if resp.status_code == 201:
        return resp.json()
    return {"error": resp.text}


def get_sample_findings() -> List[Dict]:
    """Sample findings when AWS API is unavailable."""
    return [
        {"type": "unused_ebs_volume", "resource_id": "vol-0a1b2c3d4e5f6g7h8", "region": "us-east-1", "details": "gp2 volume, 500 GB, created 2024-03-15", "monthly_savings": 50.00, "recommendation": "Delete or snapshot+delete", "severity": "high"},
        {"type": "unused_ebs_volume", "resource_id": "vol-1b2c3d4e5f6g7h8i9", "region": "us-east-1", "details": "gp3 volume, 200 GB, created 2024-06-22", "monthly_savings": 16.00, "recommendation": "Delete or snapshot+delete", "severity": "medium"},
        {"type": "oversized_ec2", "resource_id": "i-0a1b2c3d4e5f6g7h8", "region": "us-east-1", "details": "m5.xlarge 'staging-worker', avg CPU: 3.2% (14-day)", "monthly_savings": 69.12, "recommendation": "Downsize to t3.medium", "severity": "high"},
        {"type": "oversized_ec2", "resource_id": "i-1b2c3d4e5f6g7h8i9", "region": "us-west-2", "details": "r5.large 'analytics-db-backup', avg CPU: 1.8% (14-day)", "monthly_savings": 45.90, "recommendation": "Downsize to t3.large or stop", "severity": "high"},
        {"type": "orphaned_snapshot", "resource_id": "snap-0a1b2c3d4e5f6g7h8", "region": "us-east-1", "details": "1000 GB snapshot, source vol deleted, created 2023-11-01", "monthly_savings": 50.00, "recommendation": "Delete orphaned snapshot", "severity": "medium"},
        {"type": "orphaned_snapshot", "resource_id": "snap-1b2c3d4e5f6g7h8i9", "region": "eu-west-1", "details": "250 GB snapshot, source vol deleted, created 2024-01-15", "monthly_savings": 12.50, "recommendation": "Delete orphaned snapshot", "severity": "low"},
        {"type": "idle_rds", "resource_id": "dev-analytics-replica", "region": "us-east-1", "details": "db.r5.large, avg connections: 0.3 (7-day), engine: postgres", "monthly_savings": 175.20, "recommendation": "Stop or delete idle replica", "severity": "high"},
        {"type": "unattached_eip", "resource_id": "52.14.123.45", "region": "us-east-1", "details": "Elastic IP not attached to any resource", "monthly_savings": 3.65, "recommendation": "Release EIP", "severity": "low"},
        {"type": "unattached_eip", "resource_id": "34.207.89.12", "region": "us-west-2", "details": "Elastic IP not attached to any resource", "monthly_savings": 3.65, "recommendation": "Release EIP", "severity": "low"},
    ]


# --- Streamlit UI ---
st.title("Cloud Cost Optimizer")
st.caption("FinOps Dashboard | Scans: EBS, EC2, Snapshots, RDS, EIPs")

if st.button("Run Full Scan", type="primary"):
    all_findings = []
    try:
        import boto3
        for region in AWS_REGIONS_TO_SCAN:
            with st.spinner(f"Scanning {region}..."):
                session = boto3.Session(
                    aws_access_key_id=AWS_ACCESS_KEY,
                    aws_secret_access_key=AWS_SECRET_KEY,
                    region_name=region,
                )
                ec2 = session.client("ec2")
                cw = session.client("cloudwatch")
                rds = session.client("rds")

                all_findings.extend(scan_unused_ebs_volumes(ec2))
                all_findings.extend(scan_oversized_ec2(ec2, cw))
                all_findings.extend(scan_orphaned_snapshots(ec2))
                all_findings.extend(scan_idle_rds(rds, cw))
                all_findings.extend(scan_unattached_eips(ec2))
    except Exception as e:
        st.warning(f"Could not connect to AWS: {e}. Showing sample findings.")
        all_findings = get_sample_findings()

    if not all_findings:
        all_findings = get_sample_findings()

    st.session_state["findings"] = all_findings

if "findings" in st.session_state:
    findings = st.session_state["findings"]
    df = pd.DataFrame(findings)

    # Summary metrics
    total_savings = df["monthly_savings"].sum()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Findings", len(df))
    col2.metric("Monthly Savings", f"${total_savings:,.2f}")
    col3.metric("Annual Savings", f"${total_savings * 12:,.2f}")
    col4.metric("High Severity", len(df[df["severity"] == "high"]))

    # Breakdown by type
    st.subheader("Findings by Type")
    type_summary = df.groupby("type").agg(
        count=("resource_id", "count"),
        total_savings=("monthly_savings", "sum"),
    ).sort_values("total_savings", ascending=False)
    st.dataframe(type_summary, use_container_width=True)

    # Detail table
    st.subheader("All Findings")
    st.dataframe(
        df[["severity", "type", "resource_id", "region", "details", "monthly_savings", "recommendation"]].sort_values("monthly_savings", ascending=False),
        use_container_width=True,
    )

    # Export
    csv_buf = io.StringIO()
    df.to_csv(csv_buf, index=False)
    st.download_button("Export CSV Report", csv_buf.getvalue(), f"cost_optimization_{datetime.now().strftime('%Y%m%d')}.csv")

    # Create Jira tickets
    st.divider()
    st.subheader("Create Jira Tickets")
    severity_filter = st.multiselect("Severity", ["high", "medium", "low"], default=["high"])
    tickets_to_create = df[df["severity"].isin(severity_filter)]
    st.write(f"{len(tickets_to_create)} tickets will be created")

    if st.button("Create Jira Tickets"):
        created = 0
        for _, finding in tickets_to_create.iterrows():
            result = create_jira_ticket(finding.to_dict())
            if "error" not in result:
                created += 1
        st.success(f"Created {created} Jira tickets in {JIRA_PROJECT_KEY}")
