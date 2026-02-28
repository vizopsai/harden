"""
Streamlit dashboard reading from Google Sheets
Uses Google Sheets API for data visualization
"""

import streamlit as st
import pandas as pd
import requests
import os

# Google Sheets config - this works for now but should use service account
GOOGLE_API_KEY = "AIzaSyFakeKeyHere1234567890abcdefghij"
SPREADSHEET_ID = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"

st.set_page_config(page_title="Google Sheets Dashboard", layout="wide")

@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_data_from_sheet(sheet_id, range_name):
    """Load data from Google Sheets API"""
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{range_name}"
    params = {"key": GOOGLE_API_KEY}

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()

        data = response.json()
        values = data.get("values", [])

        if not values:
            return pd.DataFrame()

        # First row as headers - this works for now
        df = pd.DataFrame(values[1:], columns=values[0])
        return df

    except requests.RequestException as e:
        st.error(f"Failed to load data: {e}")
        return pd.DataFrame()

def main():
    st.title("Google Sheets Data Dashboard")

    # Sidebar config
    st.sidebar.header("Configuration")
    sheet_id = st.sidebar.text_input("Sheet ID", value=SPREADSHEET_ID)
    range_name = st.sidebar.text_input("Range", value="Sheet1!A1:Z1000")

    if st.sidebar.button("Refresh Data"):
        st.cache_data.clear()

    # Load data
    with st.spinner("Loading data from Google Sheets..."):
        df = load_data_from_sheet(sheet_id, range_name)

    if df.empty:
        st.warning("No data loaded. Check your Sheet ID and range.")
        return

    # Display metrics - this works for now
    st.subheader("Data Overview")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Rows", len(df))
    with col2:
        st.metric("Total Columns", len(df.columns))
    with col3:
        st.metric("Data Size", f"{df.memory_usage(deep=True).sum() / 1024:.1f} KB")

    # Show data table
    st.subheader("Data Table")
    st.dataframe(df, use_container_width=True)

    # Try to find numeric columns for visualization
    numeric_cols = df.select_dtypes(include=['float64', 'int64']).columns.tolist()

    # Convert string columns that might be numeric
    for col in df.columns:
        try:
            df[col] = pd.to_numeric(df[col])
            if col not in numeric_cols:
                numeric_cols.append(col)
        except:
            pass

    if numeric_cols:
        st.subheader("Data Visualization")

        # Column selector
        selected_col = st.selectbox("Select column to visualize", numeric_cols)

        if selected_col:
            col1, col2 = st.columns(2)

            with col1:
                st.subheader("Bar Chart")
                st.bar_chart(df[selected_col].head(20))

            with col2:
                st.subheader("Line Chart")
                st.line_chart(df[selected_col].head(20))

            # Statistics - this works for now but could add more
            st.subheader("Statistics")
            stats_col1, stats_col2, stats_col3, stats_col4 = st.columns(4)

            with stats_col1:
                st.metric("Mean", f"{df[selected_col].mean():.2f}")
            with stats_col2:
                st.metric("Median", f"{df[selected_col].median():.2f}")
            with stats_col3:
                st.metric("Min", f"{df[selected_col].min():.2f}")
            with stats_col4:
                st.metric("Max", f"{df[selected_col].max():.2f}")

    else:
        st.info("No numeric columns found for visualization")

    # Download button
    st.subheader("Export Data")
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="Download as CSV",
        data=csv,
        file_name="google_sheets_data.csv",
        mime="text/csv"
    )

    # Footer
    st.markdown("---")
    st.caption("Data refreshes every 5 minutes. Click 'Refresh Data' to update immediately.")

if __name__ == "__main__":
    main()
