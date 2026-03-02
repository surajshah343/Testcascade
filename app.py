import streamlit as st
import pandas as pd
import numpy as np

# Page Configuration
st.set_page_config(page_title="Fleet Cascading Dashboard", layout="wide")

def run_fleet_engine(df_f, df_c):
    # --- 1. Clean Data ---
    df_f.columns = df_f.columns.str.strip()
    df_c.columns = df_c.columns.str.strip()
    
    types = ['A', 'C', 'VAN']
    start_year = 2024
    max_end_year = int(df_c['End Year'].max())
    
    # Absolute max age across the company for retirement
    global_max_ages = {
        'A': df_c['Max age type A'].max(),
        'C': df_c['Max age type C'].max(),
        'VAN': df_c['Max age type VAN'].max()
    }
    
    current_fleet = df_f.copy()
    current_fleet['Current Age'] = pd.to_numeric(current_fleet['Current Age'], errors='coerce').fillna(0)
    
    audit_log = []
    yearly_stats = []

    # --- 2. Simulation Loop ---
    for year in range(start_year, max_end_year + 1):
        if year > start_year:
            current_fleet['Current Age'] += 1
            
        for t in types:
            # Get current fleet of this type
            type_t_fleet = current_fleet[current_fleet['Type'] == t].copy()
            
            # Identify current requirements and age limits for this year
            reqs = {}
            age_limits = {}
            for _, row in df_c.iterrows():
                loc = row['Location']
                is_active = (year <= row['End Year'])
                req_col = f'Vehicle Count {t}' if t != 'VAN' else 'Vehicle Count Van'
                reqs[loc] = int(row[req_col]) if is_active else 0
                age_limits[loc] = row[f'Max age type {t}']

            # Rebuilding the fleet assignments for this year
            new_assignments = []
            
            # Step A: Identify valid units vs. surplus
            # Pool = units that are too old for their current loc or are extra
            pool = []
            for loc, target in reqs.items():
                loc_units = type_t_fleet[type_t_fleet['Location'] == loc]
                limit = age_limits[loc]
                
                # Keep valid units up to the target count
                valid = loc_units[loc_units['Current Age'] <= limit].sort_values('Current Age', ascending=False)
                
                # If we have more valid units than needed, the youngest are spares (to be moved/cascaded)
                if len(valid) > target:
                    keep = valid.head(target)
                    spares = valid.tail(len(valid) - target)
                    new_assignments.append(keep)
                    pool.append(spares)
                else:
                    new_assignments.append(valid)
                
                # Any unit too old for its current location goes to the pool
                too_old = loc_units[loc_units['Current Age'] > limit]
                pool.append(too_old)

            # Flatten lists
            assigned_df = pd.concat(new_assignments) if new_assignments else pd.DataFrame()
            pool_df = pd.concat(pool) if pool else pd.DataFrame()

            # Step B: Fill Needs (Cascading)
            for loc, target in reqs.items():
                current_count = len(assigned_df[assigned_df['Location'] == loc]) if not assigned_df.empty else 0
                needed = target - current_count
                
                if needed > 0 and not pool_df.empty:
                    limit = age_limits[loc]
                    # Eligible units from the global pool for this location
                    eligible = pool_df[pool_df['Current Age'] <= limit].sort_values('Current Age')
                    
                    if not eligible.empty:
                        to_move = eligible.head(needed).copy()
                        for idx, row in to_move.iterrows():
                            old_loc = row['Location']
                            row['Location'] = loc
                            assigned_df = pd.concat([assigned_df, pd.DataFrame([row])])
                            pool_df = pool_df.drop(idx)
                            
                            audit_log.append({
                                "Year": year, "VIN": row['VIN'], "Type": t,
                                "Action": "CASCADE (MOVED)", "From": old_loc, "To": loc, "Age": row['Current Age']
                            })
                
                # Step C: If still needed, New Lease
                current_count = len(assigned_df[assigned_df['Location'] == loc]) if not assigned_df.empty else 0
                final_needed = target - current_count
                for _ in range(final_needed):
                    new_vin = f"LSE-{year}-{t}-{np.random.randint(100,999)}"
                    new_unit = pd.DataFrame([{
                        'VIN': new_vin, 'Model Year': year, 'Current Age': 0, 'Type': t, 'Location': loc
                    }])
                    assigned_df = pd.concat([assigned_df, new_unit])
                    audit_log.append({
                        "Year": year, "VIN": new_vin, "Type": t,
                        "Action": "NEW LEASE", "From": "FACTORY", "To": loc, "Age": 0
                    })

            # Step D: Retirement / Unassigned
            if not pool_df.empty:
                for idx, row in pool_df.iterrows():
                    if row['Current Age'] > global_max_ages[t]:
                        audit_log.append({
                            "Year": year, "VIN": row['VIN'], "Type": t,
                            "Action": "RETIRED", "From": row['Location'], "To": "SCRAP", "Age": row['Current Age']
                        })
                    else:
                        # Unit is not needed anywhere but not old enough to scrap
                        # Mark it as "Unassigned/Storage"
                        row['Location'] = "STORAGE / UNASSIGNED"
                        assigned_df = pd.concat([assigned_df, pd.DataFrame([row])])

            # Update master fleet for next year
            current_fleet = pd.concat([current_fleet[current_fleet['Type'] != t], assigned_df])

        # Yearly Statistics
        for loc in df_c['Location'].unique():
            for t in types:
                loc_fleet = current_fleet[(current_fleet['Location'] == loc) & (current_fleet['Type'] == t)]
                new_leases = len([a for a in audit_log if a['Year'] == year and a['To'] == loc and a['Action'] == "NEW LEASE" and a['Type'] == t])
                yearly_stats.append({
                    'Year': year, 'Location': loc, 'Type': t,
                    'Leases Needed': new_leases,
                    'Units Count': len(loc_fleet),
                    'Avg Age': round(loc_fleet['Current Age'].mean(), 1) if not loc_fleet.empty else 0
                })

    return pd.DataFrame(audit_log), pd.DataFrame(yearly_stats)

# --- UI ---
st.title("🚌 Intelligent Fleet Deployment & Waterfall")

file = st.file_uploader("Upload Excel Template", type=["xlsx"])

if file:
    try:
        df_c = pd.read_excel(file, sheet_name="Contracts")
        df_f = pd.read_excel(file, sheet_name="Fleet File")
        
        if st.button("Run Full Cascading Simulation"):
            audit, stats = run_fleet_engine(df_f, df_c)
            st.session_state['audit'] = audit
            st.session_state['stats'] = stats
            st.success("Simulation Complete!")

if 'audit' in st.session_state:
    st.header("📈 New Lease Waterfall (The Need)")
    t1, t2, t3 = st.tabs(["Type A", "Type C", "VAN"])
    for i, name in enumerate(['A', 'C', 'VAN']):
        with [t1, t2, t3][i]:
            df = st.session_state.stats[st.session_state.stats['Type'] == name]
            st.dataframe(df.pivot_table(index='Location', columns='Year', values='Leases Needed', aggfunc='sum'))

    st.header("🔄 Deployment Movement Log")
    st.markdown("Units moved from one location to another based on age availability.")
    cascades = st.session_state.audit[st.session_state.audit['Action'] == "CASCADE (MOVED)"]
    st.dataframe(cascades)

    st.header("🔍 VIN Lifetime Search")
    vin_id = st.text_input("Enter VIN to track its movement history:")
    if vin_id:
        history = st.session_state.audit[st.session_state.audit['VIN'].str.contains(vin_id, case=False)]
        st.dataframe(history)

    st.header("📊 Average Age (Fleet Health)")
    st.dataframe(st.session_state.stats.pivot_table(index='Location', columns='Year', values='Avg Age', aggfunc='mean'))
