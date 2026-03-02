import streamlit as st
import pandas as pd
import numpy as np

# Page Configuration
st.set_page_config(page_title="Fleet Cascading & Replacement Planner", layout="wide")

def run_fleet_engine(df_fleet, df_contracts):
    # --- Data Standardization ---
    df_fleet.columns = df_fleet.columns.str.strip()
    df_contracts.columns = df_contracts.columns.str.strip()
    
    start_year = 2024
    max_end_year = int(df_contracts['End Year'].max())
    types = ['A', 'C', 'VAN']
    
    # Global Max Age across all locations to prevent infinite loops of old buses
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
            # 1. Identify Needs & Surplus Pool
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
                
                # Add "too old" units to surplus pool (they might fit elsewhere)
                for _, row in too_old_here.iterrows():
                    surplus_pool.append({'VIN': row['VIN'], 'Age': row['Current Age'], 'From': loc})
                
                # If we have extra valid units, add them to surplus pool
                if len(valid_units) > target_qty:
                    extras = valid_units.sort_values('Current Age', ascending=True).head(len(valid_units) - target_qty)
                    for _, row in extras.iterrows():
                        surplus_pool.append({'VIN': row['VIN'], 'Age': row['Current Age'], 'From': loc})
                    # Remove from current location fleet temporarily
                    current_fleet = current_fleet[~current_fleet['VIN'].isin(extras['VIN'])]
                
                # Remove "too old" units from current location fleet temporarily
                current_fleet = current_fleet[~current_fleet['VIN'].isin(too_old_here['VIN'])]

                # Calculate remaining deficit
                if len(valid_units) < target_qty:
                    needs.append({'loc': loc, 'needed': target_qty - len(valid_units), 'max_age': max_age_loc})

            # 2. Execute Cascade & Leasing
            for need in needs:
                loc_to = need['loc']
                age_limit_to = need['max_age']
                
                for _ in range(need['needed']):
                    # Look for youngest available surplus that fits the new location's age limit
                    eligible = [u for u in surplus_pool if u['Age'] <= age_limit_to]
                    
                    if eligible:
                        chosen = min(eligible, key=lambda x: x['Age'])
                        surplus_pool.remove(chosen)
                        
                        # Move to new location
                        unit_data = df_fleet[df_fleet['VIN'] == chosen['VIN']].iloc[0:1].copy()
                        unit_data['Location'] = loc_to
                        unit_data['Current Age'] = chosen['Age']
                        current_fleet = pd.concat([current_fleet, unit_data])
                        
                        audit_log.append({
                            "Year": year, "VIN": chosen['VIN'], "Type": t, "Action": "CASCADE (MOVED)",
                            "From": chosen['From'], "To": loc_to, "Age": chosen['Age']
                        })
                    else:
                        # No surplus fits -> Lease New
                        new_vin = f"LSE-{year}-{t}-{np.random.randint(100,999)}"
                        new_row = pd.DataFrame([{'VIN': new_vin, 'Model Year': year, 'Current Age': 0, 'Type': t, 'Location': loc_to}])
                        current_fleet = pd.concat([current_fleet, new_row], ignore_index=True)
                        
                        audit_log.append({
                            "Year": year, "VIN": new_vin, "Type": t, "Action": "NEW LEASE",
                            "From": "FACTORY", "To": loc_to, "Age": 0
                        })

            # 3. Final Retirement
            for s in surplus_pool:
                if s['Age'] > global_max_ages[t]:
                    audit_log.append({
                        "Year": year, "VIN": s['VIN'], "Type": t, "Action": "RETIRED",
                        "From": s['From'], "To": "SCRAP", "Age": s['Age']
                    })

        # 4. Save Snapshot for Year-over-Year Report
        for loc in df_contracts['Location'].unique():
            for t in types:
                loc_fleet = current_fleet[(current_fleet['Location'] == loc) & (current_fleet['Type'] == t)]
                new_leases = len([a for a in audit_log if a['Year'] == year and a['To'] == loc and a['Action'] == "NEW LEASE" and a['Type'] == t])
                cascades_in = len([a for a in audit_log if a['Year'] == year and a['To'] == loc and a['Action'] == "CASCADE (MOVED)" and a['Type'] == t])
                
                yearly_stats.append({
                    'Year': year, 'Location': loc, 'Type': t,
                    'Units Needed': new_leases,
                    'Units Moved In': cascades_in,
                    'Final Fleet Count': len(loc_fleet),
                    'Avg Age': round(loc_fleet['Current Age'].mean(), 1) if not loc_fleet.empty else 0
                })

    return pd.DataFrame(audit_log), pd.DataFrame(yearly_stats)

# --- STREAMLIT UI ---
st.title("🚛 Fleet Cascading & Waterfall Dashboard")
st.markdown("This tool calculates where buses can be moved (Cascaded) based on age requirements before ordering new leases.")

uploaded_file = st.file_uploader("Upload Fleet & Contract Data (XLSX)", type=["xlsx"])

if uploaded_file:
    df_c = pd.read_excel(uploaded_file, sheet_name="Contracts")
    df_f = pd.read_excel(uploaded_file, sheet_name="Fleet File")
    
    if st.button("Generate Detailed Breakdown"):
        audit_df, stats_df = run_fleet_engine(df_f, df_c)
        
        # --- TOP LEVEL SUMMARY ---
        st.header("📈 Executive Waterfall Summary")
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("New Leases Needed (Yearly)")
            lease_pivot = stats_df.pivot_table(index='Location', columns='Year', values='Units Needed', aggfunc='sum')
            st.dataframe(lease_pivot.style.highlight_max(axis=0, color='#ffcccc'), use_container_width=True)
            
        with col2:
            st.subheader("Average Fleet Age")
            age_pivot = stats_df.pivot_table(index='Location', columns='Year', values='Avg Age', aggfunc='mean')
            st.dataframe(age_pivot.style.background_gradient(cmap='YlOrRd'), use_container_width=True)

        # --- MOVEMENT TRACKING ---
        st.header("🔄 Deployment & Movement Log")
        st.markdown("Clearly tracking where fleet was moved **FROM** and **TO**.")
        
        # Filter for movements and new leases only
        move_only = audit_df[audit_df['Action'] != 'RETIRED']
        st.dataframe(move_only[['Year', 'Action', 'VIN', 'Type', 'From', 'To', 'Age']], use_container_width=True)

        # --- PER LOCATION BREAKDOWNS ---
        st.header("📍 Location Specific Deep-Dive")
        locations = df_c['Location'].unique()
        loc_tabs = st.tabs(list(locations))
        
        for i, loc in enumerate(locations):
            with loc_tabs[i]:
                st.subheader(f"Forecast for {loc}")
                
                # Show Year-by-Year breakdown for this location
                loc_summary = stats_df[stats_df['Location'] == loc].drop(columns=['Location'])
                st.table(loc_summary.set_index(['Year', 'Type']))
                
                # Show specific VIN actions for this location
                st.markdown("**Specific VIN Actions at this Location:**")
                loc_audit = audit_df[(audit_df['To'] == loc) | (audit_df['From'] == loc)]
                if not loc_audit.empty:
                    st.dataframe(loc_audit.drop(columns=['Type']), use_container_width=True)
                else:
                    st.write("No specific movements or leases for this location.")

        # Download Links
        st.divider()
        csv_audit = audit_df.to_csv(index=False).encode('utf-8')
        st.download_button("Download Full Audit Trail (CSV)", data=csv_audit, file_name="fleet_audit_trail.csv")
