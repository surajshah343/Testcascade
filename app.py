import streamlit as st
import pandas as pd
import numpy as np

# Page Configuration
st.set_page_config(page_title="Fleet Spare-First Cascading", layout="wide")

def run_fleet_engine(df_fleet, df_contracts):
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
            surplus_pool = [] # Global pool of spares available for redeployment
            
            # --- STEP 1: CALCULATE SPARES & DEFICITS ---
            for loc in df_contracts['Location'].unique():
                c_row = df_contracts[df_contracts['Location'] == loc].iloc[0]
                is_active = (year <= c_row['End Year'])
                req_col = f'Vehicle Count {t}' if t != 'VAN' else 'Vehicle Count Van'
                target_qty = int(c_row[req_col]) if is_active else 0
                max_age_loc = c_row[f'Max age type {t}']
                
                # All units currently assigned to this location
                loc_units = current_fleet[(current_fleet['Location'] == loc) & (current_fleet['Type'] == t)]
                
                # Identify units that are VALID (under age) vs EXPIRED (over age)
                valid_units = loc_units[loc_units['Current Age'] <= max_age_loc]
                expired_units = loc_units[loc_units['Current Age'] > max_age_loc]
                
                # Move EXPIRED units to surplus pool (they might fit in a more lenient contract)
                for _, row in expired_units.iterrows():
                    surplus_pool.append({'VIN': row['VIN'], 'Age': row['Current Age'], 'From': loc, 'Expired': True})
                current_fleet = current_fleet[~current_fleet['VIN'].isin(expired_units['VIN'])]
                
                # Identify SPARES (Valid units exceeding the target count)
                if len(valid_units) > target_qty:
                    # Take the YOUNGEST spares to move elsewhere
                    num_spares = len(valid_units) - target_qty
                    spares = valid_units.sort_values('Current Age', ascending=True).head(num_spares)
                    for _, row in spares.iterrows():
                        surplus_pool.append({'VIN': row['VIN'], 'Age': row['Current Age'], 'From': loc, 'Expired': False})
                    current_fleet = current_fleet[~current_fleet['VIN'].isin(spares['VIN'])]
                
                # Identify DEFICITS (Targets not met by valid units)
                if len(valid_units) < target_qty:
                    needs.append({'loc': loc, 'needed': target_qty - len(valid_units), 'max_age': max_age_loc})

            # --- STEP 2: FILL DEFICITS USING SURPLUS POOL ---
            for need in needs:
                loc_to = need['loc']
                age_limit_to = need['max_age']
                
                for _ in range(need['needed']):
                    # Filter surplus pool for any unit that fits this specific location's age limit
                    eligible = [u for u in surplus_pool if u['Age'] <= age_limit_to]
                    
                    if eligible:
                        # Prioritize using units that weren't "expired" first (true spares), then aged units
                        chosen = min(eligible, key=lambda x: x['Age'])
                        surplus_pool.remove(chosen)
                        
                        # Re-attach unit to fleet at new location
                        unit_data = df_fleet[df_fleet['VIN'] == chosen['VIN']].iloc[0:1].copy()
                        unit_data['Location'] = loc_to
                        unit_data['Current Age'] = chosen['Age']
                        current_fleet = pd.concat([current_fleet, unit_data])
                        
                        audit_log.append({
                            "Year": year, "VIN": chosen['VIN'], "Type": t, "Action": "CASCADE (SPARE)",
                            "From": chosen['From'], "To": loc_to, "Age": chosen['Age']
                        })
                    else:
                        # No suitable spares? Trigger Lease.
                        new_vin = f"LSE-{year}-{t}-{np.random.randint(100,999)}"
                        new_row = pd.DataFrame([{'VIN': new_vin, 'Model Year': year, 'Current Age': 0, 'Type': t, 'Location': loc_to}])
                        current_fleet = pd.concat([current_fleet, new_row], ignore_index=True)
                        
                        audit_log.append({
                            "Year": year, "VIN": new_vin, "Type": t, "Action": "NEW LEASE",
                            "From": "FACTORY", "To": loc_to, "Age": 0
                        })

            # --- STEP 3: SCRAP THE REST ---
            for s in surplus_pool:
                if s['Age'] > global_max_ages[t]:
                    audit_log.append({
                        "Year": year, "VIN": s['VIN'], "Type": t, "Action": "RETIRED",
                        "From": s['From'], "To": "SCRAP", "Age": s['Age']
                    })

        # --- STEP 4: RECORD SNAPSHOTS ---
        for loc in df_contracts['Location'].unique():
            for t in types:
                loc_fleet = current_fleet[(current_fleet['Location'] == loc) & (current_fleet['Type'] == t)]
                new_leases = len([a for a in audit_log if a['Year'] == year and a['To'] == loc and a['Action'] == "NEW LEASE" and a['Type'] == t])
                
                yearly_stats.append({
                    'Year': year, 'Location': loc, 'Type': t,
                    'New Leases Needed': new_leases,
                    'Final Fleet Count': len(loc_fleet),
                    'Avg Age': round(loc_fleet['Current Age'].mean(), 1) if not loc_fleet.empty else 0
                })

    return pd.DataFrame(audit_log), pd.DataFrame(yearly_stats)

# --- STREAMLIT UI ---
st.title("🚛 Fleet Spare-First Deployment Dashboard")
st.markdown("""
**Logic Applied:** 1. Identify **Spares** (Units > Required Count) at each site.
2. Identify **Young Units** from the spares pool.
3. Move those spares to locations with deficits.
4. Only lease new vehicles if the global spare pool is empty or too old for the target site.
""")

uploaded_file = st.file_uploader("Upload Fleet & Contract Data (XLSX)", type=["xlsx"])

if uploaded_file:
    try:
        df_c = pd.read_excel(uploaded_file, sheet_name="Contracts", engine='openpyxl')
        df_f = pd.read_excel(uploaded_file, sheet_name="Fleet File", engine='openpyxl')
        
        if st.button("Generate Cascading Analysis"):
            audit_df, stats_df = run_fleet_engine(df_f, df_c)
            
            # --- OUTPUT 1: WATERFALL BY TYPE ---
            st.header("📈 New Lease Waterfall (By Type)")
            tabs = st.tabs(["Type A", "Type C", "VAN"])
            for i, t in enumerate(["A", "C", "VAN"]):
                with tabs[i]:
                    t_df = stats_df[stats_df['Type'] == t]
                    st.dataframe(t_df.pivot_table(index='Location', columns='Year', values='New Leases Needed', aggfunc='sum'), use_container_width=True)

            # --- OUTPUT 2: MOVEMENT LOG ---
            st.header("🔄 Spare Movement Log")
            moves = audit_df[audit_df['Action'] == 'CASCADE (SPARE)']
            st.dataframe(moves[['Year', 'VIN', 'Type', 'From', 'To', 'Age']], use_container_width=True)

            # --- OUTPUT 3: MATURITY ---
            st.header("📊 Age by Location & Year")
            st.dataframe(stats_df.pivot_table(index='Location', columns='Year', values='Avg Age', aggfunc='mean'), use_container_width=True)

    except Exception as e:
        st.error(f"Error: {e}")
