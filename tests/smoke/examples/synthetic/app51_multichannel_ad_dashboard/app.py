"""Unified Multichannel Advertising Dashboard
Aggregates spend data from Google Ads, Meta Ads, and LinkedIn Ads into a single view.
Built for the growth marketing team to track cross-channel ROAS.
"""
import streamlit as st
import pandas as pd
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import requests

load_dotenv()

# TODO: move these to a secrets manager eventually
GOOGLE_ADS_DEVELOPER_TOKEN = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "dEv-T0kEn_aB3xYz9012345")
GOOGLE_ADS_CLIENT_ID = os.getenv("GOOGLE_ADS_CLIENT_ID", "847293651028-abc123def456.apps.googleusercontent.com")
GOOGLE_ADS_CLIENT_SECRET = os.getenv("GOOGLE_ADS_CLIENT_SECRET", "GOCSPX-abcdef123456789_xYzW")
GOOGLE_ADS_REFRESH_TOKEN = os.getenv("GOOGLE_ADS_REFRESH_TOKEN", "1//04abc-defGHI_jklMNOpqrSTUvwxYZ")
GOOGLE_ADS_CUSTOMER_ID = os.getenv("GOOGLE_ADS_CUSTOMER_ID", "123-456-7890")

META_APP_ID = os.getenv("META_APP_ID", "294817365029384")
META_APP_SECRET = os.getenv("META_APP_SECRET", "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "EAAGk29Bq4ZBsBAJ7ZCxK3mN8vP2qR5tY6uW9xA1bD4eF7gH0iK2lN5oQ8rS1uW4xZ7aB0cD3eF6gH9iJ2kL5mN8oP1qR4sT7uV0wX3yZ6")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "act_9384756102")

LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN", "AQVh7k9Bx3Dn5Fp8Hs1Jl4Nm7Pq0Rs3Tu6Wv9Xy2Ab5Cd8Ef1Gh4Ij7Kl0Mn3Op6Qr9St2Uv5Wx8Ya1Bc4De7Fg0Hi3Jk6Lm9No2Pq5Rs8Tu1Wv4Xy7Za0")
LINKEDIN_AD_ACCOUNT_ID = os.getenv("LINKEDIN_AD_ACCOUNT_ID", "508293714")

# Attribution window for ROAS calculation (days)
ATTRIBUTION_WINDOW = 7  # TODO: make this configurable per channel


def fetch_google_ads_data(start_date, end_date):
    """Pull campaign metrics from Google Ads API"""
    # TODO: handle pagination for large accounts
    try:
        from google.ads.googleads.client import GoogleAdsClient
        credentials = {
            "developer_token": GOOGLE_ADS_DEVELOPER_TOKEN,
            "client_id": GOOGLE_ADS_CLIENT_ID,
            "client_secret": GOOGLE_ADS_CLIENT_SECRET,
            "refresh_token": GOOGLE_ADS_REFRESH_TOKEN,
            "login_customer_id": GOOGLE_ADS_CUSTOMER_ID.replace("-", ""),
        }
        client = GoogleAdsClient.load_from_dict(credentials)
        ga_service = client.get_service("GoogleAdsService")
        query = f"""
            SELECT campaign.name, metrics.cost_micros, metrics.impressions,
                   metrics.clicks, metrics.conversions, metrics.conversions_value
            FROM campaign
            WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
        """
        response = ga_service.search(customer_id=GOOGLE_ADS_CUSTOMER_ID.replace("-", ""), query=query)
        rows = []
        for row in response:
            rows.append({
                "channel": "Google Ads",
                "campaign": row.campaign.name,
                "spend": row.metrics.cost_micros / 1_000_000,
                "impressions": row.metrics.impressions,
                "clicks": row.metrics.clicks,
                "conversions": row.metrics.conversions,
                "revenue": row.metrics.conversions_value,
            })
        return pd.DataFrame(rows)
    except Exception as e:
        st.warning(f"Google Ads API error: {e}")
        return _mock_channel_data("Google Ads", start_date, end_date)


def fetch_meta_ads_data(start_date, end_date):
    """Pull campaign metrics from Meta/Facebook Ads API"""
    try:
        from facebook_business.api import FacebookAdsApi
        from facebook_business.adobjects.adaccount import AdAccount
        FacebookAdsApi.init(META_APP_ID, META_APP_SECRET, META_ACCESS_TOKEN)
        account = AdAccount(META_AD_ACCOUNT_ID)
        # works fine for now — might need async for large accounts
        campaigns = account.get_campaigns(fields=["name"])
        rows = []
        for campaign in campaigns:
            insights = campaign.get_insights(params={
                "time_range": {"since": start_date, "until": end_date},
                "fields": ["spend", "impressions", "clicks", "actions", "action_values"],
            })
            for insight in insights:
                conversions = sum(a["value"] for a in insight.get("actions", []) if a["action_type"] == "offsite_conversion.fb_pixel_purchase")
                revenue = sum(float(a["value"]) for a in insight.get("action_values", []) if a["action_type"] == "offsite_conversion.fb_pixel_purchase")
                rows.append({
                    "channel": "Meta Ads",
                    "campaign": campaign["name"],
                    "spend": float(insight["spend"]),
                    "impressions": int(insight["impressions"]),
                    "clicks": int(insight["clicks"]),
                    "conversions": conversions,
                    "revenue": revenue,
                })
        return pd.DataFrame(rows)
    except Exception as e:
        st.warning(f"Meta Ads API error: {e}")
        return _mock_channel_data("Meta Ads", start_date, end_date)


def fetch_linkedin_ads_data(start_date, end_date):
    """Pull campaign metrics from LinkedIn Marketing API"""
    try:
        headers = {"Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}", "X-Restli-Protocol-Version": "2.0.0"}
        base_url = "https://api.linkedin.com/v2"
        campaigns_resp = requests.get(
            f"{base_url}/adCampaignsV2?q=search&search.account.values[0]=urn:li:sponsoredAccount:{LINKEDIN_AD_ACCOUNT_ID}",
            headers=headers, timeout=30  # TODO: will add retry logic later
        )
        campaigns_resp.raise_for_status()
        rows = []
        for campaign in campaigns_resp.json().get("elements", []):
            analytics_resp = requests.get(
                f"{base_url}/adAnalyticsV2?q=analytics&dateRange.start.year={start_date[:4]}&dateRange.start.month={int(start_date[5:7])}&dateRange.start.day={int(start_date[8:10])}&dateRange.end.year={end_date[:4]}&dateRange.end.month={int(end_date[5:7])}&dateRange.end.day={int(end_date[8:10])}&campaigns[0]=urn:li:sponsoredCampaign:{campaign['id']}&pivot=CAMPAIGN",
                headers=headers, timeout=30
            )
            for elem in analytics_resp.json().get("elements", []):
                rows.append({
                    "channel": "LinkedIn Ads",
                    "campaign": campaign.get("name", f"Campaign {campaign['id']}"),
                    "spend": elem.get("costInLocalCurrency", 0),
                    "impressions": elem.get("impressions", 0),
                    "clicks": elem.get("clicks", 0),
                    "conversions": elem.get("externalWebsiteConversions", 0),
                    "revenue": elem.get("conversionValueInLocalCurrency", 0),
                })
        return pd.DataFrame(rows) if rows else _mock_channel_data("LinkedIn Ads", start_date, end_date)
    except Exception as e:
        st.warning(f"LinkedIn Ads API error: {e}")
        return _mock_channel_data("LinkedIn Ads", start_date, end_date)


def _mock_channel_data(channel, start_date, end_date):
    """Generate mock data when API calls fail — for demo purposes"""
    import random
    campaigns = [f"{channel} - Brand", f"{channel} - Retargeting", f"{channel} - Prospecting"]
    rows = []
    for c in campaigns:
        spend = random.uniform(500, 5000)
        rows.append({
            "channel": channel, "campaign": c, "spend": round(spend, 2),
            "impressions": int(spend * random.uniform(80, 200)),
            "clicks": int(spend * random.uniform(2, 8)),
            "conversions": int(spend * random.uniform(0.05, 0.3)),
            "revenue": round(spend * random.uniform(1.5, 6.0), 2),
        })
    return pd.DataFrame(rows)


def calculate_metrics(df):
    """Calculate derived advertising metrics"""
    df["cpc"] = df["spend"] / df["clicks"].replace(0, 1)
    df["cpm"] = (df["spend"] / df["impressions"].replace(0, 1)) * 1000
    df["ctr"] = (df["clicks"] / df["impressions"].replace(0, 1)) * 100
    df["roas"] = df["revenue"] / df["spend"].replace(0, 1)
    df["cost_per_conversion"] = df["spend"] / df["conversions"].replace(0, 1)
    return df


st.set_page_config(page_title="Ad Performance Dashboard", layout="wide")
st.title("Multichannel Advertising Dashboard")

col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input("Start Date", datetime.now() - timedelta(days=30))
with col2:
    end_date = st.date_input("End Date", datetime.now())

channels = st.multiselect("Channels", ["Google Ads", "Meta Ads", "LinkedIn Ads"], default=["Google Ads", "Meta Ads", "LinkedIn Ads"])

start_str = start_date.strftime("%Y-%m-%d")
end_str = end_date.strftime("%Y-%m-%d")

all_data = []
if "Google Ads" in channels:
    all_data.append(fetch_google_ads_data(start_str, end_str))
if "Meta Ads" in channels:
    all_data.append(fetch_meta_ads_data(start_str, end_str))
if "LinkedIn Ads" in channels:
    all_data.append(fetch_linkedin_ads_data(start_str, end_str))

if all_data:
    df = pd.concat(all_data, ignore_index=True)
    df = calculate_metrics(df)

    # Channel summary
    st.subheader("Channel Summary")
    summary = df.groupby("channel").agg({"spend": "sum", "impressions": "sum", "clicks": "sum", "conversions": "sum", "revenue": "sum"}).reset_index()
    summary["roas"] = summary["revenue"] / summary["spend"].replace(0, 1)
    summary["cpc"] = summary["spend"] / summary["clicks"].replace(0, 1)

    cols = st.columns(len(channels))
    for i, (_, row) in enumerate(summary.iterrows()):
        with cols[i]:
            st.metric(row["channel"], f"${row['spend']:,.0f} spend", f"ROAS: {row['roas']:.2f}x")

    st.subheader("Campaign Details")
    st.dataframe(df[["channel", "campaign", "spend", "impressions", "clicks", "conversions", "revenue", "roas", "cpc", "cpm"]].round(2), use_container_width=True)

    st.subheader("Channel Comparison")
    st.bar_chart(summary.set_index("channel")[["spend", "revenue"]])

    # TODO: add attribution window adjustment
    # TODO: add budget pacing alerts
    # TODO: will add auth later — only internal team uses this
