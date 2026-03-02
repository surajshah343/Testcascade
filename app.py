import streamlit as st
import pandas as pd
import numpy as np

# Page Configuration
st.set_page_config(page_title="Fleet Cascading Dashboard", layout="wide")

def run_fleet_engine(df_f, df_c):
    # --- 1. Clean Data & Headers ---
    df_f.columns = df_f.columns.str.strip()
    df_c.columns = df_c.columns.str.strip()
    
    # Identify unique types present in the fleet to avoid "not found in axis" errors
    types = [t for t in ['A', 'C', 'VAN'] if t in df_f['Type'].unique() or t in df_c.columns.get_level_values(0)]
    if not types: types = ['A', 'C', 'VAN'] # Fallback
    
    start_year = 2024
    max_end_year = int(df_c['End Year'].max())
    
    # Absolute max age across the company for retirement
    global_max_ages = {
        'A': df_c['Max age type A'].max() if 'Max age type A' in df_c.columns else 10,
        'C': df_c['Max age type C'].max() if 'Max age type C' in df_c.columns else 10,
        'VAN': df_c['Max age type VAN'].max() if 'Max age type VAN' in df_c.columns else 10
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
            # Requirements and age limits for this year/type
            reqs = {}
            age_limits = {}
            for _, row in df_c.iterrows():
                loc = row['Location']
                is_active = (year <= row['End Year'])
                req_col = f'Vehicle Count {t}' if t != 'VAN' else 'Vehicle Count Van'
                
                # Safety check for column existence
                if req_col in df_c.columns:
                    reqs[loc] = int(row[req_col]) if is_active else 0
                    age_limits[loc] = row[f'Max age type {t}']
                else:
                    reqs[loc] = 0
                    age_limits[loc] = 10

            # --- CASCADING LOGIC ---
            type_t_fleet = current_fleet[current_fleet['Type'] == t].copy()
            pool = []
            assigned_df = pd.DataFrame()

            for loc, target in reqs.items():
                loc_units = type_t_fleet[type_t_fleet['Location'] == loc]
                limit = age_limits[loc]
                
                valid = loc_units[loc_units['Current Age'] <= limit].sort_values('Current Age', ascending=False)
                
                if len(valid) > target:
                    keep = valid.head(target)
                    spares = valid.tail(len(valid) - target)
                    assigned_df = pd.concat([assigned_df, keep])
                    pool.append(spares)
                else:
                    assigned_df = pd.concat([assigned_df, valid])
                
                too_old = loc_units[loc_units['Current Age'] > limit]
                pool.append(too_old)

            pool_df = pd.concat(pool) if pool else pd.DataFrame()

            # Fill Deficits
            for loc, target in reqs.items():
                current_count = len(assigned_df[assigned_df['Location'] == loc]) if not assigned_df.empty else 0
                needed = target - current_count
                
                if needed > 0 and not pool_df.empty:
                    limit = age_limits[loc]
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

            # New Lease
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

            # Retirement
            if not pool_df.empty:
                for idx, row in pool_df.iterrows():
                    if row['Current Age'] > global_max_ages.get(t, 15):
                        audit_log.append({
                            "Year": year, "VIN": row['VIN'], "Type": t,
                            "Action": "RETIRED", "From": row['Location'], "To": "SCRAP", "Age": row['Current Age']
                        })
                    else:
                        row['Location'] = "UNASSIGNED SPARE"
                        assigned_df = pd.concat([assigned_df, pd.DataFrame([row])])

            current_fleet = pd.concat([current_fleet[current_fleet['Type'] != t], assigned_df])

        # Stats Collection
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

file = st.file_uploader("Upload Excel", type=["xlsx"])

if file:
    try:
        df_c = pd.read_excel(file, sheet_name="Contracts", engine='openpyxl')
        df_f = pd.read_excel(file, sheet_name="Fleet File", engine='openpyxl')
        
        if st.button("Run Simulation"):
            audit, stats = run_fleet_engine(df_f, df_c)
            st.session_state['audit'] = audit
            st.session_state['stats'] = stats
            st.success("Simulation Complete!")
            
    except Exception as e:
        st.error(f"Error: {e}")

# --- SAFE OUTPUT SECTION ---
if 'audit' in st.session_state and not st.session_state.stats.empty:
    st.header("📈 New Lease Waterfall")
    
    # Break out by Type
    for t_name in st.session_state.stats['Type'].unique():
        st.subheader(f"Type {t_name} Requirements")
        df_t = st.session_state.stats[st.session_state.stats['Type'] == t_name]
        
        if not df_t.empty:
            pivot = df_t.pivot_table(index='Location', columns='Year', values='Leases Needed', aggfunc='sum', fill_value=0)
            st.dataframe(pivot, use_container_width=True)

    st.header("🔄 Movement Log")
    cascades = st.session_state.audit[st.session_state.audit['Action'] == "CASCADE (MOVED)"]
    st.dataframe(cascades, use_container_width=True)

    st.header("📊 Maturity Matrix (Avg Age)")
    if not st.session_state.stats.empty:
        age_pivot = st.session_state.stats.pivot_table(index='Location', columns='Year', values='Avg Age', aggfunc='mean', fill_value=0)
        st.dataframe(age_pivot, use_container_width=True)
