import streamlit as st
import pandas as pd
import numpy as np

# Page Configuration
st.set_page_config(page_title="VIN-Level Fleet Auditor", layout="wide")

def run_vin_level_simulation(df_fleet, df_contracts):
    """
    Detailed simulation that tracks every VIN movement.
    """
    # 1. Setup & Automatic Horizon Calculation
    df_fleet.columns = df_fleet.columns.str.strip()
    df_contracts.columns = df_contracts.columns.str.strip()
    
    start_year = 2024
    max_end_year = int(df_contracts['End Year'].max())
    horizon = max_end_year - start_year
    
    types = ['A', 'C', 'VAN']
    current_fleet = df_fleet.copy()
    current_fleet['Current Age'] = pd.to_numeric(current_fleet['Current Age'], errors='coerce').fillna(0)
    
    vin_audit_trail = [] # To store every move
    annual_summary = []  # To store counts

    for year in range(start_year, max_end_year + 1):
        if year > start_year:
            current_fleet['Current Age'] += 1
            
        # --- Phase 1: Retirement ---
        to_retire_indices = []
        for idx, row in current_fleet.iterrows():
            loc = row['Location']
            vtype = str(row['Type']).upper()
            contract = df_contracts[df_contracts['Location'] == loc]
            
            if not contract.empty:
                max_age_col = f'Max age type {vtype}'
                limit = contract.iloc[0][max_age_col]
                if row['Current Age'] > limit:
                    to_retire_indices.append(idx)
                    vin_audit_trail.append({
                        "Year": year, "VIN": row['VIN'], "Type": vtype,
                        "Action": "RETIRED", "From": loc, "To": "OFF-LEASE", "Reason": f"Age {row['Current Age']} > {limit}"
                    })
        
        current_fleet = current_fleet.drop(to_retire_indices)

        # --- Phase 2: Balancing (Cascading & Leasing) ---
        for t in types:
            needs = []
            surplus_vins = []
            
            for loc in df_contracts['Location'].unique():
                c_row = df_contracts[df_contracts['Location'] == loc].iloc[0]
                is_active = (year <= c_row['End Year'])
                req_col = f'Vehicle Count {t}' if t != 'VAN' else 'Vehicle Count Van'
                target_qty = int(c_row[req_col]) if is_active else 0
                
                loc_units = current_fleet[(current_fleet['Location'] == loc) & (current_fleet['Type'] == t)]
                current_qty = len(loc_units)
                
                if current_qty > target_qty:
                    # Collect surplus (youngest first)
                    extras = loc_units.sort_values('Current Age', ascending=True).head(current_qty - target_qty)
                    for _, row in extras.iterrows():
                        surplus_vins.append({'vin': row['VIN'], 'orig_loc': loc})
                elif current_qty < target_qty:
                    needs.append({'loc': loc, 'needed': target_qty - current_qty})

            # Execute Moves
            for need in needs:
                for _ in range(need['needed']):
                    if surplus_vins:
                        move_data = surplus_vins.pop(0)
                        vin_to_move = move_data['vin']
                        
                        # Update Fleet
                        current_fleet.loc[current_fleet['VIN'] == vin_to_move, 'Location'] = need['loc']
                        
                        vin_audit_trail.append({
                            "Year": year, "VIN": vin_to_move, "Type": t,
                            "Action": "CASCADED", "From": move_data['orig_loc'], "To": need['loc'], "Reason": "Redeployed Surplus"
                        })
                    else:
                        # New Lease
                        new_vin = f"LSE-{year}-{t}-{np.random.randint(1000,9999)}"
                        new_row = pd.DataFrame([{
                            'VIN': new_vin, 'Model Year': year, 'Current Age': 0, 'Type': t, 'Location': need['loc']
                        }])
                        current_fleet = pd.concat([current_fleet, new_row], ignore_index=True)
                        
                        vin_audit_trail.append({
                            "Year": year, "VIN": new_vin, "Type": t,
                            "Action": "NEW LEASE", "From": "FACTORY", "To": need['loc'], "Reason": "No Surplus Available"
                        })

    return pd.DataFrame(vin_audit_trail), current_fleet

# --- STREAMLIT UI ---
st.title("🚌 VIN-Level Fleet Waterfall & Cascade Auditor")

uploaded_file = st.file_uploader("Upload Fleet & Contracts Excel", type=["xlsx"])

if uploaded_file:
    try:
        df_contracts = pd.read_excel(uploaded_file, sheet_name="Contracts", engine='openpyxl')
        df_fleet = pd.read_excel(uploaded_file, sheet_name="Fleet File", engine='openpyxl')
        
        # Auto-detect Horizon
        max_yr = int(df_contracts['End Year'].max())
        st.sidebar.metric("Simulating Until Year", max_yr)

        if st.button("Generate Detailed VIN Audit"):
            audit_df, final_fleet = run_vin_level_simulation(df_fleet, df_contracts)
            
            # 1. The Audit Trail (Where are they moving?)
            st.header("📍 VIN Movement Log (The Waterfall)")
            st.markdown("This table shows every specific bus that was retired, moved (cascaded), or leased.")
            
            # Filter for the Audit Trail
            search_vin = st.text_input("Search by VIN (e.g., LSE-2025-A-1234)")
            if search_vin:
                display_audit = audit_df[audit_df['VIN'].str.contains(search_vin, case=False)]
            else:
                display_audit = audit_df
            
            st.dataframe(display_audit, use_container_width=True)

            # 2. Summary by Year
            st.header("📊 Annual Activity Summary")
            summary_pivot = audit_df.pivot_table(
                index=['Action', 'Type'], 
                columns='Year', 
                values='VIN', 
                aggfunc='count', 
                fill_value=0
            )
            st.table(summary_pivot)

            # 3. Downloads
            col1, col2 = st.columns(2)
            with col1:
                csv_audit = audit_df.to_csv(index=False).encode('utf-8')
                st.download_button("Download VIN Audit Trail", data=csv_audit, file_name="vin_movement_audit.csv")
            with col2:
                csv_final = final_fleet.to_csv(index=False).encode('utf-8')
                st.download_button("Download Year-End Fleet State", data=csv_final, file_name="final_fleet_projection.csv")

    except Exception as e:
        st.error(f"Critical Error: {e}")
