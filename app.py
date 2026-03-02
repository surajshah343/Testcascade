import streamlit as st
import pandas as pd
import numpy as np

# Page Configuration
st.set_page_config(page_title="Fleet Cascading Dashboard", layout="wide")

def run_fleet_engine(df_f, df_c):
    # --- 1. Clean Data & Headers ---
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
            # Identify current requirements and age limits for this year/type
            reqs = {}
            age_limits = {}
            for _, row in df_c.iterrows():
                loc = row['Location']
                is_active = (year <= row['End Year'])
                req_col = f'Vehicle Count {t}' if t != 'VAN' else 'Vehicle Count Van'
                reqs[loc] = int(row[req_col]) if is_active else 0
                age_limits[loc] = row[f'Max age type {t}']

            # Step A: Create a Global Surplus Pool for Type T
            # We take EVERYTHING out and put it back where it fits best
            type_t_fleet = current_fleet[current_fleet['Type'] == t].copy()
            pool = []
            assigned_df = pd.DataFrame()

            for loc, target in reqs.items():
                loc_units = type_t_fleet[type_t_fleet['Location'] == loc]
                limit = age_limits[loc]
                
                # Split units into "Valid for this Location" vs "Must be moved/retired"
                valid = loc_units[loc_units['Current Age'] <= limit].sort_values('Current Age', ascending=False)
                
                # If we have more valid units than needed, the YOUNGEST are spares (best for cascading)
                if len(valid) > target:
                    keep = valid.head(target)
                    spares = valid.tail(len(valid) - target)
                    assigned_df = pd.concat([assigned_df, keep])
                    pool.append(spares)
                else:
                    assigned_df = pd.concat([assigned_df, valid])
                
                # Units too old for current loc go to pool (e.g. Brantford 9yr old)
                too_old = loc_units[loc_units['Current Age'] > limit]
                pool.append(too_old)

            pool_df = pd.concat(pool) if pool else pd.DataFrame()

            # Step B: Fill Deficits (The Cascade)
            # Prioritize moving surplus units to locations in need
            for loc, target in reqs.items():
                current_count = len(assigned_df[assigned_df['Location'] == loc]) if not assigned_df.empty else 0
                needed = target - current_count
                
                if needed > 0 and not pool_df.empty:
                    limit = age_limits[loc]
                    # Find units in pool that are young enough for this location
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

            # Step C: Lease New if pool couldn't fill the gap
            for loc, target in reqs.items():
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

            # Step D: Retirement
            if not pool_df.empty:
                for idx, row in pool_df.iterrows():
                    if row['Current Age'] > global_max_ages[t]:
                        audit_log.append({
                            "Year": year, "VIN": row['VIN'], "Type": t,
                            "Action": "RETIRED", "From": row['Location'], "To": "SCRAP", "Age": row['Current Age']
                        })
                    else:
                        # Unit is a spare not needed this year
                        row['Location'] = "UNASSIGNED SPARE"
                        assigned_df = pd.concat([assigned_df, pd.DataFrame([row])])

            # Update master fleet
            current_fleet = pd.concat([current_fleet[current_fleet['Type'] != t], assigned_df])

        # Record Yearly Stats
        for loc in df_c['Location'].unique():
            for t in types:
                loc_fleet = current_fleet[(current_fleet['Location'] == loc) & (current_fleet['Type'] == t)]
                new_leases = len([a for a in audit_log if a['Year'] == year and a['To'] == loc and a['Action'] == "NEW LEASE" and a['Type'] == t])
                yearly_stats.append({
                    'Year': year, 'Location': loc, 'Type': t,
                    'Leases Needed': new_leases,
                    'Unit Count': len(loc_fleet),
                    'Avg Age': round(loc_fleet['Current Age'].mean(), 1) if not loc_fleet.empty else 0
                })

    return pd.DataFrame(audit_log), pd.DataFrame(yearly_stats)

# --- UI INTERFACE ---
st.title("🚌 Fleet Waterfall & Cascading Dashboard")

file = st.file_uploader("Upload Excel with 'Contracts' and 'Fleet File' tabs", type=["xlsx"])

if file:
    try:
        df_c = pd.read_excel(file, sheet_name="Contracts", engine='openpyxl')
        df_f = pd.read_excel(file, sheet_name="Fleet File", engine='openpyxl')
        
        if st.button("Run Full Cascading Simulation"):
            audit, stats = run_fleet_engine(df_f, df_c)
            st.session_state['audit'] = audit
            st.session_state['stats'] = stats
            st.success("Simulation Complete!")
            
    except Exception as e:
        st.error(f"Error processing file: {e}")

# --- OUTPUT SECTION ---
if 'audit' in st.session_state:
    st.header("📈 New Lease Waterfall (By Type)")
    t1, t2, t3 = st.tabs(["Type A", "Type C", "VAN"])
    for i, name in enumerate(['A', 'C', 'VAN']):
        with [t1, t2, t3][i]:
            df = st.session_state.stats[st.session_state.stats['Type'] == name]
            st.dataframe(df.pivot_table(index='Location', columns='Year', values='Leases Needed', aggfunc='sum'), use_container_width=True)

    st.header("🔄 Deployment Movement Log")
    cascades = st.session_state.audit[st.session_state.audit['Action'] == "CASCADE (MOVED)"]
    st.dataframe(cascades, use_container_width=True)

    st.header("🔍 Unit-Level Search")
    vin_id = st.text_input("Enter VIN to track its movement (e.g., track a Brantford bus):")
    if vin_id:
        history = st.session_state.audit[st.session_state.audit['VIN'].str.contains(vin_id, case=False, na=False)]
        st.dataframe(history, use_container_width=True)

    st.header("📊 Fleet Maturity (Avg Age)")
    st.dataframe(st.session_state.stats.pivot_table(index='Location', columns='Year', values='Avg Age', aggfunc='mean'), use_container_width=True)
