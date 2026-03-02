import streamlit as st
import pandas as pd
import numpy as np

# Page Configuration
st.set_page_config(page_title="Fleet Cascading & Waterfall", layout="wide")

def run_fleet_engine(df_fleet, df_contracts):
    # --- Data Standardization ---
    df_fleet.columns = df_fleet.columns.str.strip()
    df_contracts.columns = df_contracts.columns.str.strip()
    
    start_year = 2024
    # Automatically determine forecast length from the furthest contract end date
    max_end_year = int(df_contracts['End Year'].max())
    types = ['A', 'C', 'VAN']
    
    # Global Max Age across all locations to prevent infinite loops
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
                
                # Split units into "Fits Here" vs "Must Leave"
                too_old_here = loc_units[loc_units['Current Age'] > max_age_loc]
                valid_units = loc_units[loc_units['Current Age'] <= max_age_loc]
                
                # Surplus handling
                for _, row in too_old_here.iterrows():
                    surplus_pool.append({'VIN': row['VIN'], 'Age': row['Current Age'], 'From': loc})
                
                if len(valid_units) > target_qty:
                    extras = valid_units.sort_values('Current Age', ascending=True).head(len(valid_units) - target_qty)
                    for _, row in extras.iterrows():
                        surplus_pool.append({'VIN': row['VIN'], 'Age': row['Current Age'], 'From': loc})
                    current_fleet = current_fleet[~current_fleet['VIN'].isin(extras['VIN'])]
                
                current_fleet = current_fleet[~current_fleet['VIN'].isin(too_old_here['VIN'])]

                if len(valid_units) < target_qty:
                    needs.append({'loc': loc, 'needed': target_qty - len(valid_units), 'max_age': max_age_loc})

            # Cascading & Leasing
            for need in needs:
                loc_to = need['loc']
                age_limit_to = need['max_age']
                
                for _ in range(need['needed']):
                    eligible = [u for u in surplus_pool if u['Age'] <= age_limit_to]
                    
                    if eligible:
                        chosen = min(eligible, key=lambda x: x['Age'])
                        surplus_pool.remove(chosen)
                        
                        unit_data = df_fleet[df_fleet['VIN'] == chosen['VIN']].iloc[0:1].copy()
                        unit_data['Location'] = loc_to
                        unit_data['Current Age'] = chosen['Age']
                        current_fleet = pd.concat([current_fleet, unit_data])
                        
                        audit_log.append({
                            "Year": year, "VIN": chosen['VIN'], "Type": t, "Action": "CASCADE (MOVED)",
                            "From": chosen['From'], "To": loc_to, "Age": chosen['Age']
                        })
                    else:
                        new_vin = f"LSE-{year}-{t}-{np.random.randint(100,999)}"
                        new_row = pd.DataFrame([{'VIN': new_vin, 'Model Year': year, 'Current Age': 0, 'Type': t, 'Location': loc_to}])
                        current_fleet = pd.concat([current_fleet, new_row], ignore_index=True)
                        
                        audit_log.append({
                            "Year": year, "VIN": new_vin, "Type": t, "Action": "NEW LEASE",
                            "From": "FACTORY", "To": loc_to, "Age": 0
                        })

            for s in surplus_pool:
                if s['Age'] > global_max_ages[t]:
                    audit_log.append({
                        "Year": year, "VIN": s['VIN'], "Type": t, "Action": "RETIRED",
                        "From": s['From'], "To": "SCRAP", "Age": s['Age']
                    })

        # Year-End Snapshot
        for loc in df_contracts['Location'].unique():
            for t in types:
                loc_fleet = current_fleet[(current_fleet['Location'] == loc) & (current_fleet['Type'] == t)]
                new_leases = len([a for a in audit_log if a['Year'] == year and a['To'] == loc and a['Action'] == "NEW LEASE" and a['Type'] == t])
                cascades_in = len([a for a in audit_log if a['Year'] == year and a['To'] == loc and a['Action'] == "CASCADE (MOVED)" and a['Type'] == t])
                
                yearly_stats.append({
                    'Year': year, 'Location': loc, 'Type': t,
                    'Units Needed (Lease)': new_leases,
                    'Units Moved In (Cascade)': cascades_in,
                    'Final Fleet Count': len(loc_fleet),
                    'Avg Age': round(loc_fleet['Current Age'].mean(), 1) if not loc_fleet.empty else 0
                })

    return pd.DataFrame(audit_log), pd.DataFrame(yearly_stats)

# --- UI ---
st.title("🚌 Fleet Waterfall & Type-Specific Need Analysis")

uploaded_file = st.file_uploader("Upload Fleet & Contract Data (XLSX)", type=["xlsx"])

if uploaded_file:
    try:
        df_c = pd.read_excel(uploaded_file, sheet_name="Contracts", engine='openpyxl')
        df_f = pd.read_excel(uploaded_file, sheet_name="Fleet File", engine='openpyxl')
        
        if st.button("Generate Detailed Breakdown"):
            audit_df, stats_df = run_fleet_engine(df_f, df_c)
            
            st.header("📈 New Lease Needs (By Type)")
            st.markdown("This section breaks down exactly how many new leases are needed per year, separated by vehicle category.")
            
            # Use Tabs for different types to keep the UI clean
            type_tabs = st.tabs(["Type A Needs", "Type C Needs", "Van Needs"])
            
            for i, t_name in enumerate(["A", "C", "VAN"]):
                with type_tabs[i]:
                    st.subheader(f"New Lease Waterfall: Type {t_name}")
                    type_df = stats_df[stats_df['Type'] == t_name]
                    lease_pivot = type_df.pivot_table(index='Location', columns='Year', values='Units Needed (Lease)', aggfunc='sum')
                    st.dataframe(lease_pivot, use_container_width=True)
            
            st.divider()

            # --- CASCADING LOG ---
            st.header("🔄 Deployment & Movement Log")
            st.markdown("Tracking VINs that were moved (Cascaded) instead of leased.")
            move_only = audit_df[audit_df['Action'] == 'CASCADE (MOVED)']
            st.dataframe(move_only[['Year', 'VIN', 'Type', 'From', 'To', 'Age']], use_container_width=True)

            # --- MATURITY MATRIX ---
            st.header("📊 Average Fleet Age by Location")
            age_pivot = stats_df.pivot_table(index='Location', columns='Year', values='Avg Age', aggfunc='mean')
            st.dataframe(age_pivot, use_container_width=True)

            # --- LOCATION DEEP DIVE ---
            st.header("📍 Location Specific View")
            locations = df_c['Location'].unique()
            loc_tabs = st.tabs(list(locations))
            
            for i, loc in enumerate(locations):
                with loc_tabs[i]:
                    loc_summary = stats_df[stats_df['Location'] == loc].drop(columns=['Location'])
                    st.table(loc_summary.set_index(['Year', 'Type']))
                    
                    st.markdown("**Action Log for this Location:**")
                    loc_audit = audit_df[(audit_df['To'] == loc) | (audit_df['From'] == loc)]
                    st.dataframe(loc_audit.drop(columns=['Type']), use_container_width=True)

    except Exception as e:
        st.error(f"Error: {e}")
