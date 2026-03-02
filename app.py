import streamlit as st
import pandas as pd
import numpy as np

# Set page config
st.set_page_config(page_title="Fleet Waterfall Analyst", layout="wide")

def process_cascading_fleet(df_fleet, df_contracts, years=5):
    """
    Simulates fleet aging. When a VIN > Max Age, it triggers a lease (Age 0).
    """
    # Standardize column names to avoid Case Sensitivity issues
    df_fleet.columns = df_fleet.columns.str.strip().str.title()
    df_contracts.columns = df_contracts.columns.str.strip().str.title()
    
    # Create a mapping for Max Age by Type
    # Expected columns: 'Type', 'Max Age'
    age_limit_map = dict(zip(df_contracts['Type'], df_contracts['Max Age']))
    
    history = []
    # Work on a copy of the fleet to simulate aging
    sim_fleet = df_fleet.copy()
    
    current_year = 2024 # Starting Point
    
    for y in range(1, years + 1):
        year_label = current_year + y
        
        # 1. Age the existing fleet
        sim_fleet['Current Age'] += 1
        
        # 2. Check for expirations and group by Location/Type
        for (loc, v_type), group in sim_fleet.groupby(['Location', 'Type']):
            max_allowed = age_limit_map.get(v_type, 10) # Default 10 if not found
            
            # Count how many exceeded the limit this year
            expired_mask = (sim_fleet['Location'] == loc) & \
                           (sim_fleet['Type'] == v_type) & \
                           (sim_fleet['Current Age'] > max_allowed)
            
            num_expired = expired_mask.sum()
            
            # Waterfall stats
            history.append({
                "Year": year_label,
                "Location": loc,
                "Type": v_type,
                "Active Units": len(group),
                "Expired/Replaced": num_expired,
                "Avg Age": group['Current Age'].mean()
            })
            
            # 3. CASCADING: Replace expired units with new leases (Age 0)
            # This keeps the fleet count constant but resets age for those VINs
            sim_fleet.loc[expired_mask, 'Current Age'] = 0
            
    return pd.DataFrame(history)

## --- UI INTERFACE ---
st.title("🚛 Fleet Cascading & Lease Waterfall")
st.markdown("""
Upload your Excel file. 
* **Tab 1:** Should contain Contract Info (`Type`, `Max Age`).
* **Tab 2:** Should contain Fleet Info (`VIN`, `Type`, `Location`, `Current Age`).
""")

uploaded_file = st.file_uploader("Upload Fleet Excel File", type=["xlsx"])

if uploaded_file:
    try:
        # Load sheets
        contracts_df = pd.read_excel(uploaded_file, sheet_name=0)
        fleet_df = pd.read_excel(uploaded_file, sheet_name=1)
        
        st.success("File Loaded Successfully!")
        
        # Sidebar Controls
        st.sidebar.header("Simulation Parameters")
        forecast_years = st.sidebar.slider("Forecast Horizon (Years)", 1, 15, 5)
        
        # Run Calculation
        waterfall_results = process_cascading_fleet(fleet_df, contracts_df, forecast_years)
        
        # --- DISPLAY RESULTS ---
        
        # 1. Summary Table (Pivot)
        st.subheader("New Leases Required (Waterfall by Year)")
        pivot_waterfall = waterfall_results.pivot_table(
            index=['Location', 'Type'], 
            columns='Year', 
            values='Expired/Replaced', 
            aggfunc='sum'
        )
        st.dataframe(pivot_waterfall.style.background_gradient(cmap="Oranges"), use_container_width=True)
        
        # 2. Detailed View
        with st.expander("View Detailed Annual Metrics (Age & Counts)"):
            st.write(waterfall_results)
            
        # 3. Total Replacement Summary
        st.subheader("Total Replacements Needed over Forecast Period")
        summary = waterfall_results.groupby('Type')['Expired/Replaced'].sum().reset_name('Total New Leases')
        st.bar_chart(waterfall_results, x="Year", y="Expired/Replaced", color="Type")

    except Exception as e:
        st.error(f"Error: Ensure your Excel tabs and columns match the requirements. Details: {e}")
else:
    st.info("Awaiting file upload...")
