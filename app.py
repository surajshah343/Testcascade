import streamlit as st
import pandas as pd
import numpy as np

# Page Configuration
st.set_page_config(page_title="Fleet Cascading & Waterfall", layout="wide")

def run_fleet_simulation(df_fleet, df_contracts, horizon_years=5):
    """
    Simulates fleet lifecycles:
    1. Ages vehicles annually.
    2. Retires vehicles exceeding Max Age.
    3. Cascades surplus units from ending/downsizing locations to sites in need.
    4. Issues new leases only as a last resort.
    """
    # Standardize column cleaning
    df_fleet.columns = df_fleet.columns.str.strip()
    df_contracts.columns = df_contracts.columns.str.strip()
    
    # Identify types based on the contracts tab
    types = ['A', 'C', 'VAN']
    current_fleet = df_fleet.copy()
    current_fleet['Current Age'] = pd.to_numeric(current_fleet['Current Age'], errors='coerce').fillna(0)
    
    results = []
    start_year = 2024 # Assumed base year
    
    # Tracking for the "Waterfall"
    for year in range(start_year, start_year + horizon_years + 1):
        # 1. Aging (Increment age every year after the first)
        if year > start_year:
            current_fleet['Current Age'] += 1
            
        # 2. Retirement: Drop units that exceed the Max Age limit
        to_retire_indices = []
        for idx, row in current_fleet.iterrows():
            loc = row['Location']
            vtype = str(row['Type']).upper()
            contract = df_contracts[df_contracts['Location'] == loc]
            if not contract.empty:
                max_age_col = f'Max age type {vtype}'
                if max_age_col in contract.columns:
                    limit = contract.iloc[0][max_age_col]
                    if row['Current Age'] > limit:
                        to_retire_indices.append(idx)
        
        # Log retired count for the year
        retired_units = current_fleet.loc[to_retire_indices].copy()
        current_fleet = current_fleet.drop(to_retire_indices)

        # 3. Balancing (Cascading & New Leases) per Vehicle Type
        for t in types:
            needs = []
            surplus_vins = []
            
            # Identify Deficits and Surplus across all locations for Type T
            for loc in df_contracts['Location'].unique():
                c_row = df_contracts[df_contracts['Location'] == loc].iloc[0]
                
                # Logic: If Year > End Year, the requirement is 0
                is_contract_active = (year <= c_row['End Year'])
                req_col = f'Vehicle Count {t}' if t != 'VAN' else 'Vehicle Count Van'
                target_qty = c_row[req_col] if is_contract_active else 0
                
                loc_units = current_fleet[(current_fleet['Location'] == loc) & (current_fleet['Type'] == t)]
                current_qty = len(loc_units)
                
                if current_qty > target_qty:
                    # Collect surplus VINs (youngest first to maximize redeployment life)
                    extras = loc_units.sort_values('Current Age', ascending=True).head(int(current_qty - target_qty))
                    surplus_vins.extend(extras['VIN'].tolist())
                elif current_qty < target_qty:
                    needs.append({'loc': loc, 'needed': int(target_qty - current_qty)})

            # 4. Process the Cascade
            new_leases_this_type = {}
            cascades_in_this_type = {}

            for need in needs:
                loc = need['loc']
                qty = need['needed']
                cascades_in_this_type[loc] = 0
                new_leases_this_type[loc] = 0
                
                for _ in range(qty):
                    if surplus_vins:
                        # Move existing unit to new location
                        vin_to_move = surplus_vins.pop(0)
                        current_fleet.loc[current_fleet['VIN'] == vin_to_move, 'Location'] = loc
                        cascades_in_this_type[loc] += 1
                    else:
                        # No surplus available in the company -> Sign New Lease
                        new_vin = f"LSE-{year}-{t}-{np.random.randint(1000,9999)}"
                        new_row = pd.DataFrame([{
                            'VIN': new_vin, 'Model Year': year, 'Current Age': 0, 'Type': t, 'Location': loc
                        }])
                        current_fleet = pd.concat([current_fleet, new_row], ignore_index=True)
                        new_leases_this_type[loc] += 1

            # 5. Log Year-End Snapshot for this Type
            for loc in df_contracts['Location'].unique():
                final_loc_fleet = current_fleet[(current_fleet['Location'] == loc) & (current_fleet['Type'] == t)]
                results.append({
                    'Year': year,
                    'Location': loc,
                    'Type': t,
                    'Target Count': df_contracts[df_contracts['Location'] == loc].iloc[0][f'Vehicle Count {t}' if t != 'VAN' else 'Vehicle Count Van'] if year <= df_contracts[df_contracts['Location'] == loc].iloc[0]['End Year'] else 0,
                    'Actual Count': len(final_loc_fleet),
                    'Retired': len(retired_units[(retired_units['Location'] == loc) & (retired_units['Type'] == t)]),
                    'Cascaded In': cascades_in_this_type.get(loc, 0),
                    'New Leases': new_leases_this_type.get(loc, 0),
                    'Avg Age': final_loc_fleet['Current Age'].mean() if not final_loc_fleet.empty else 0
                })

    return pd.DataFrame(results)

# --- UI INTERFACE ---
st.title("🚛 Fleet Cascading Waterfall & Replacement Planner")
st.info("Logic: Units move from ended/downsized contracts to active ones before new leases are triggered.")

uploaded_file = st.file_uploader("Upload your Fleet & Contracts Excel", type=["xlsx"])

if uploaded_file:
    try:
        # Load sheets
        df_contracts = pd.read_excel(uploaded_file, sheet_name="Contracts", engine='openpyxl')
        df_fleet = pd.read_excel(uploaded_file, sheet_name="Fleet File", engine='openpyxl')
        
        st.sidebar.header("Simulation Parameters")
        horizon = st.sidebar.slider("Projection Years", 1, 10, 5)
        
        if st.button("Run Cascading Analysis"):
            with st.spinner("Simulating vehicle movements..."):
                wf_df = run_fleet_simulation(df_fleet, df_contracts, horizon)
            
            # --- 1. THE WATERFALL: NEW LEASES ---
            st.subheader("New Leases Needed (Waterfall)")
            lease_pivot = wf_df.pivot_table(index=['Location', 'Type'], columns='Year', values='New Leases', aggfunc='sum')
            st.dataframe(lease_pivot, use_container_width=True)
            
            # --- 2. THE CASCADE: REDEPLOYMENTS ---
            st.subheader("Cascaded Units (Moves between Locations)")
            cascade_pivot = wf_df.pivot_table(index=['Location', 'Type'], columns='Year', values='Cascaded In', aggfunc='sum')
            st.dataframe(cascade_pivot, use_container_width=True)
            
            # --- 3. DETAILED ANALYTICS ---
            st.subheader("Detailed Annual Report (Age & Count)")
            st.dataframe(wf_df, use_container_width=True)
            
            # Download
            csv = wf_df.to_csv(index=False).encode('utf-8')
            st.download_button("Download Full Waterfall CSV", data=csv, file_name="fleet_cascade_report.csv")

    except Exception as e:
        st.error(f"Error: Ensure your column names match exactly. Details: {e}")
else:
    st.write("Awaiting Excel file with 'Contracts' and 'Fleet File' tabs.")
