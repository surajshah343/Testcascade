import streamlit as st
import pandas as pd
import numpy as np

# Page Configuration
st.set_page_config(page_title="Fleet Lifecycle Auditor", layout="wide")

def run_fleet_engine(df_fleet, df_contracts):
    # --- Data Cleaning ---
    df_fleet.columns = df_fleet.columns.str.strip()
    df_contracts.columns = df_contracts.columns.str.strip()
    
    start_year = 2024
    max_end_year = int(df_contracts['End Year'].max())
    types = ['A', 'C', 'VAN']
    
    global_max_ages = {
        'A': df_contracts['Max age type A'].max(),
        'C': df_contracts['Max age type C'].max(),
        'VAN': df_contracts['Max age type VAN'].max()
    }
    
    current_fleet = df_fleet.copy()
    current_fleet['Current Age'] = pd.to_numeric(current_fleet['Current Age'], errors='coerce').fillna(0)
    
    audit_log = []
    yearly_stats = []

    for year in range(start_year, max_end_year + 1):
        if year > start_year:
            current_fleet['Current Age'] += 1
            
        for t in types:
            needs = []
            surplus_pool = []
            
            for loc in df_contracts['Location'].unique():
                c_row = df_contracts[df_contracts['Location'] == loc].iloc[0]
                is_active = (year <= c_row['End Year'])
                req_col = f'Vehicle Count {t}' if t != 'VAN' else 'Vehicle Count Van'
                target_qty = int(c_row[req_col]) if is_active else 0
                max_age_loc = c_row[f'Max age type {t}']
                
                loc_units = current_fleet[(current_fleet['Location'] == loc) & (current_fleet['Type'] == t)]
                valid_units = loc_units[loc_units['Current Age'] <= max_age_loc]
                expired_units = loc_units[loc_units['Current Age'] > max_age_loc]
                
                # Capture Expired units for potential cascade elsewhere
                for _, row in expired_units.iterrows():
                    surplus_pool.append({'VIN': row['VIN'], 'Age': row['Current Age'], 'From': loc, 'Status': 'Expired locally'})
                current_fleet = current_fleet[~current_fleet['VIN'].isin(expired_units['VIN'])]
                
                # Capture Spares (Extra units beyond requirement)
                if len(valid_units) > target_qty:
                    num_spares = len(valid_units) - target_qty
                    spares = valid_units.sort_values('Current Age', ascending=True).head(num_spares)
                    for _, row in spares.iterrows():
                        surplus_pool.append({'VIN': row['VIN'], 'Age': row['Current Age'], 'From': loc, 'Status': 'Spare'})
                    current_fleet = current_fleet[~current_fleet['VIN'].isin(spares['VIN'])]
                
                if len(valid_units) < target_qty:
                    needs.append({'loc': loc, 'needed': target_qty - len(valid_units), 'max_age': max_age_loc})

            # Re-homing logic
            for need in needs:
                for _ in range(need['needed']):
                    eligible = [u for u in surplus_pool if u['Age'] <= need['max_age']]
                    if eligible:
                        chosen = min(eligible, key=lambda x: x['Age'])
                        surplus_pool.remove(chosen)
                        
                        unit_data = df_fleet[df_fleet['VIN'] == chosen['VIN']].iloc[0:1].copy()
                        unit_data['Location'] = need['loc']
                        unit_data['Current Age'] = chosen['Age']
                        current_fleet = pd.concat([current_fleet, unit_data])
                        
                        audit_log.append({
                            "Year": year, "VIN": chosen['VIN'], "Type": t, "Action": "CASCADED",
                            "From": chosen['From'], "To": need['loc'], "Age": chosen['Age'], "Note": f"Re-homed as {chosen['Status']}"
                        })
                    else:
                        new_vin = f"LSE-{year}-{t}-{np.random.randint(100,999)}"
                        new_row = pd.DataFrame([{'VIN': new_vin, 'Model Year': year, 'Current Age': 0, 'Type': t, 'Location': need['loc']}])
                        current_fleet = pd.concat([current_fleet, new_row], ignore_index=True)
                        audit_log.append({"Year": year, "VIN": new_vin, "Type": t, "Action": "NEW LEASE", "From": "FACTORY", "To": need['loc'], "Age": 0, "Note": "Gap fill"})

            # Scrapping
            for s in surplus_pool:
                if s['Age'] > global_max_ages[t]:
                    audit_log.append({"Year": year, "VIN": s['VIN'], "Type": t, "Action": "RETIRED", "From": s['From'], "To": "SCRAP", "Age": s['Age'], "Note": "Over global limit"})

        # Record Snapshots
        for loc in df_contracts['Location'].unique():
            for t in types:
                loc_fleet = current_fleet[(current_fleet['Location'] == loc) & (current_fleet['Type'] == t)]
                yearly_stats.append({
                    'Year': year, 'Location': loc, 'Type': t,
                    'Leases': len([a for a in audit_log if a['Year'] == year and a['To'] == loc and a['Action'] == "NEW LEASE" and a['Type'] == t]),
                    'Count': len(loc_fleet), 'AvgAge': round(loc_fleet['Current Age'].mean(), 1) if not loc_fleet.empty else 0
                })

    return pd.DataFrame(audit_log), pd.DataFrame(yearly_stats)

# --- UI ---
st.title("🚌 Fleet Lifecycle & Movement Auditor")

uploaded_file = st.file_uploader("Upload Fleet & Contract Data", type=["xlsx"])

if uploaded_file:
    df_c = pd.read_excel(uploaded_file, sheet_name="Contracts", engine='openpyxl')
    df_f = pd.read_excel(uploaded_file, sheet_name="Fleet File", engine='openpyxl')
    
    if st.button("Run Full Simulation"):
        # Store results in session state so they persist for the search box
        st.session_state.audit_trail, st.session_state.stats = run_fleet_engine(df_f, df_c)
        st.success("Simulation Complete!")

# Only show outputs if simulation has been run
if 'audit_trail' in st.session_state:
    st.header("📊 Annual Lease Waterfall")
    tabs = st.tabs(["Type A", "Type C", "VAN"])
    for i, t in enumerate(["A", "C", "VAN"]):
        with tabs[i]:
            t_df = st.session_state.stats[st.session_state.stats['Type'] == t]
            st.dataframe(t_df.pivot_table(index='Location', columns='Year', values='Leases', aggfunc='sum'), use_container_width=True)

    # --- THE NEW SEARCH BOX ---
    st.divider()
    st.header("🔍 Unit-Level History Search")
    st.markdown("Enter a **VIN** below to see exactly what happened to that specific vehicle across all years.")
    
    search_vin = st.text_input("Enter VIN Number:", placeholder="Example: V123456 or LSE-2025-A-123")
    
    if search_vin:
        # Search for exact matches or partial strings
        unit_history = st.session_state.audit_trail[st.session_state.audit_trail['VIN'].str.contains(search_vin, case=False, na=False)]
        
        if not unit_history.empty:
            st.subheader(f"History for VIN: {search_vin}")
            # Display history in a clean chronological list
            for _, row in unit_history.sort_values('Year').iterrows():
                with st.expander(f"Year {row['Year']}: {row['Action']}"):
                    st.write(f"**From:** {row['From']} ➡️ **To:** {row['To']}")
                    st.write(f"**Age at time of action:** {row['Age']}")
                    st.write(f"**Notes:** {row['Note']}")
            
            st.dataframe(unit_history, use_container_width=True)
        else:
            st.warning("No movement history found for that VIN. It may have stayed at its original location for the entire period.")

    # Show Average Age Matrix
    st.header("📈 Maturity Matrix (Avg Age)")
    st.dataframe(st.session_state.stats.pivot_table(index='Location', columns='Year', values='AvgAge', aggfunc='mean'), use_container_width=True)
