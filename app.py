import streamlit as st
import pandas as pd
import numpy as np

# Page Configuration
st.set_page_config(page_title="Fleet Cascading Waterfall", layout="wide")

def run_fleet_model(df_fleet, df_contracts, projection_years=5):
    # 1. Setup Data Structures
    # Convert Contracts (Wide) to a more usable dictionary/lookup
    # Expecting: Location, Max age type A, Max age type C, Max age type VAN, Vehicle Count A, etc.
    contracts = df_contracts.set_index('Location').to_dict('index')
    
    # Define mapping between Type in Fleet and Column Suffix in Contracts
    type_map = {'A': 'A', 'C': 'C', 'VAN': 'VAN'}
    
    current_fleet = df_fleet.copy()
    current_fleet['Current Age'] = pd.to_numeric(current_fleet['Current Age'], errors='coerce').fillna(0)
    
    results = []
    start_year = 2024

    for year_idx in range(1, projection_years + 1):
        year = start_year + year_idx
        
        # Step A: Age the fleet
        current_fleet['Current Age'] += 1
        
        # Step B: Retire units that exceed Max Age
        for loc in contracts.keys():
            for t_code in ['A', 'C', 'VAN']:
                max_age_col = f'Max age type {t_code}'
                max_age = contracts[loc].get(max_age_col, 10)
                
                # Identify expired units at this location
                expired_mask = (current_fleet['Location'] == loc) & \
                               (current_fleet['Type'] == t_code) & \
                               (current_fleet['Current Age'] > max_age)
                
                # Remove them from the active fleet
                num_retired = expired_mask.sum()
                current_fleet = current_fleet[~expired_mask]

        # Step C: Balancing & Cascading
        # We look for Deficits vs Surplus across all locations
        for t_code in ['A', 'C', 'VAN']:
            count_col = f'Vehicle Count {t_code}'
            
            # 1. Identify locations needing units (Deficit) and having extra (Surplus)
            deficits = {}
            surplus_pool = pd.DataFrame()

            for loc in contracts.keys():
                required = contracts[loc].get(count_col, 0)
                actual = len(current_fleet[(current_fleet['Location'] == loc) & (current_fleet['Type'] == t_code)])
                diff = required - actual
                
                if diff > 0:
                    deficits[loc] = diff
                elif diff < 0:
                    # Collect surplus units (take the youngest ones first to cascade)
                    loc_surplus = current_fleet[(current_fleet['Location'] == loc) & (current_fleet['Type'] == t_code)]
                    loc_surplus = loc_surplus.sort_values('Current Age').head(abs(diff))
                    surplus_pool = pd.concat([surplus_pool, loc_surplus])
            
            # 2. Execute Cascade (Move from surplus pool to deficit locations)
            for loc_need, qty_needed in deficits.items():
                new_leases_this_loc = 0
                cascaded_in_this_loc = 0
                
                for _ in range(qty_needed):
                    if not surplus_pool.empty:
                        # Take the youngest unit from the surplus pool
                        unit_to_move = surplus_pool.iloc[0].copy()
                        surplus_pool = surplus_pool.iloc[1:]
                        
                        # Update its location in the main fleet
                        idx = current_fleet[current_fleet['VIN'] == unit_to_move['VIN']].index[0]
                        current_fleet.at[idx, 'Location'] = loc_need
                        cascaded_in_this_loc += 1
                    else:
                        # No surplus left anywhere? Must Lease New
                        new_unit = {
                            'VIN': f'NEW-{year}-{loc_need}-{t_code}-{np.random.randint(1000,9999)}',
                            'Type': t_code,
                            'Location': loc_need,
                            'Current Age': 0,
                            'Model Year': year
                        }
                        current_fleet = pd.concat([current_fleet, pd.DataFrame([new_unit])], ignore_index=True)
                        new_leases_this_loc += 1
                
                # Log stats for this Year/Loc/Type
                results.append({
                    "Year": year,
                    "Location": loc_need,
                    "Type": t_code,
                    "Required": contracts[loc_need].get(count_col, 0),
                    "Cascaded In": cascaded_in_this_loc,
                    "New Leases": new_leases_this_loc,
                    "Current Fleet Count": len(current_fleet[(current_fleet['Location'] == loc_need) & (current_fleet['Type'] == t_code)])
                })

    return pd.DataFrame(results)

# --- Streamlit UI ---
st.title("Fleet Waterfall & Cascading Modeler")

uploaded_file = st.file_uploader("Upload Fleet & Contract Excel", type=["xlsx"])

if uploaded_file:
    try:
        # Load sheets with exact names provided
        df_contracts = pd.read_excel(uploaded_file, sheet_name="Contracts")
        df_fleet = pd.read_excel(uploaded_file, sheet_name="Fleet File")
        
        st.sidebar.header("Simulation Settings")
        horizon = st.sidebar.slider("Projection Horizon (Years)", 1, 10, 5)
        
        if st.button("Generate Waterfall Analysis"):
            with st.spinner("Calculating cascades..."):
                wf_report = run_fleet_model(df_fleet, df_contracts, horizon)
            
            st.success("Analysis Complete")
            
            # --- 1. Total New Leases Required (Waterfall) ---
            st.subheader("New Leases Triggered (by Year)")
            lease_pivot = wf_report.pivot_table(
                index=['Location', 'Type'], 
                columns='Year', 
                values='New Leases', 
                aggfunc='sum',
                fill_value=0
            )
            st.dataframe(lease_pivot.style.background_gradient(cmap="Reds"), use_container_width=True)
            
            # --- 2. Cascading Movements ---
            st.subheader("Cascaded Units (Inter-Location Transfers)")
            cascade_pivot = wf_report.pivot_table(
                index=['Location', 'Type'], 
                columns='Year', 
                values='Cascaded In', 
                aggfunc='sum',
                fill_value=0
            )
            st.dataframe(cascade_pivot.style.background_gradient(cmap="Greens"), use_container_width=True)
            
            # --- 3. Detailed Data Download ---
            st.subheader("Full Annual Detailed Waterfall")
            st.dataframe(wf_report, use_container_width=True)
            
            csv = wf_report.to_csv(index=False).encode('utf-8')
            st.download_button("Download Full Report CSV", data=csv, file_name="fleet_waterfall_report.csv")

    except Exception as e:
        st.error(f"Error processing file. Please check tab names and headers. Details: {e}")
else:
    st.info("Please upload an Excel file with 'Contracts' and 'Fleet File' tabs.")
