import streamlit as st
import pandas as pd
import numpy as np

# Page Config
st.set_page_config(page_title="Fleet Cascading & Lease Modeler", layout="wide")

## --- Helper Functions ---
def run_cascading_logic(df_fleet, df_contracts, projection_years=5):
    """
    Simulates fleet aging and cascading replacement over X years.
    """
    results = []
    # Work on a copy to avoid mutating original data
    current_fleet = df_fleet.copy()
    
    # Extract Max Age from contracts (assuming one max age per Type)
    # If it's by location, adjust the grouping accordingly
    max_age_map = df_contracts.set_index('Type')['Max Age'].to_dict()

    for year in range(2025, 2025 + projection_years):
        # 1. Age the fleet
        current_fleet['Current Age'] += 1
        
        # 2. Identify expired units
        for vehicle_type in current_fleet['Type'].unique():
            limit = max_age_map.get(vehicle_type, 10) # Default to 10 if not found
            
            for location in current_fleet['Location'].unique():
                mask = (current_fleet['Location'] == location) & (current_fleet['Type'] == vehicle_type)
                loc_fleet = current_fleet[mask]
                
                expired_count = len(loc_fleet[loc_fleet['Current Age'] > limit])
                active_count = len(loc_fleet[loc_fleet['Current Age'] <= limit])
                
                # Logic: Replace expired units with new Leases (Age 0)
                # To "Cascade", we'd look if other locations have surplus, 
                # but per your prompt, we trigger a lease if max age is exceeded.
                new_leases_needed = expired_count
                
                # Record Snapshot
                results.append({
                    "Year": year,
                    "Location": location,
                    "Type": vehicle_type,
                    "Total Units": len(loc_fleet),
                    "Active (Under Max)": active_count,
                    "Expired (Over Max)": expired_count,
                    "New Leases Triggered": new_leases_needed,
                    "Avg Age": loc_fleet['Current Age'].mean()
                })
                
                # Update fleet for next year: Remove expired, add new leases
                # In a real cascade, we'd move VINs here. For this model, we refresh the age.
                current_fleet.loc[mask & (current_fleet['Current Age'] > limit), 'Current Age'] = 0

    return pd.DataFrame(results)

## --- UI Layout ---
st.title("🚛 Fleet Cascading & Waterfall Analysis")
st.markdown("Upload your Excel file to calculate lease requirements and fleet aging.")

uploaded_file = st.file_uploader("Upload Fleet & Contract Excel", type=["xlsx"])

if uploaded_file:
    # 1. Load Data
    try:
        df_contracts = pd.read_excel(uploaded_file, sheet_name=0)
        df_fleet = pd.read_excel(uploaded_file, sheet_name=1)
        
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Contract Parameters")
            st.dataframe(df_contracts, use_container_width=True)
        with col2:
            st.subheader("Current Fleet Preview")
            st.dataframe(df_fleet.head(), use_container_width=True)

        # 2. Configuration Sidebar
        st.sidebar.header("Simulation Settings")
        years_to_forecast = st.sidebar.slider("Forecast Horizon (Years)", 1, 10, 5)
        
        # 3. Process Logic
        if st.button("Run Waterfall Analysis"):
            waterfall_df = run_cascading_logic(df_fleet, df_contracts, years_to_forecast)
            
            st.divider()
            st.header("Detailed Waterfall Report")
            
            # 4. Visualization - Pivot Table Style
            waterfall_pivot = waterfall_df.pivot_table(
                index=["Location", "Type"], 
                columns="Year", 
                values="New Leases Triggered",
                agg_values='sum'
            )
            
            st.subheader("New Leases Required by Year")
            st.dataframe(waterfall_pivot.style.highlight_max(axis=0), use_container_width=True)
            
            st.subheader("Full Fleet Health Snapshot")
            st.dataframe(waterfall_df, use_container_width=True)
            
            # Download button
            csv = waterfall_df.to_csv(index=False).encode('utf-8')
            st.download_button("Download Full Waterfall CSV", data=csv, file_name="fleet_waterfall.csv")

    except Exception as e:
        st.error(f"Error processing file: {e}. Please ensure Tab 1 is 'Contracts' and Tab 2 is 'Fleet'.")
else:
    st.info("Expecting an Excel file with:\n1. Tab 1: Contracts (Type, Max Age)\n2. Tab 2: Fleet (VIN, Type, Location, Current Age)")
