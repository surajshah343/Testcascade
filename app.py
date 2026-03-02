import streamlit as st
import pandas as pd
import numpy as np

# Page Configuration
st.set_page_config(page_title="Fleet Cascading Dashboard", layout="wide")

def clean_df(df):
    """Standardize column names: remove spaces and make lowercase for internal logic."""
    df.columns = df.columns.astype(str).str.strip().str.lower()
    return df

def run_fleet_engine(df_f, df_c):
    # --- 1. Clean & Standardize Input Data ---
    df_f = clean_df(df_f)
    df_c = clean_df(df_c)
    
    # Map internal logic names back to your specific Excel headers
    # We look for the closest match for 'type', 'location', 'vin', etc.
    start_year = 2024
    
    # Auto-detect the 'end year' column
    end_year_col = [c for c in df_c.columns if 'end' in c and 'year' in c][0]
    max_end_year = int(df_c[end_year_col].max())
    
    types = ['a', 'c', 'van']
    current_fleet = df_f.copy()
    
    # Ensure 'current age' exists and is numeric
    age_col = [c for c in df_f.columns if 'age' in c][0]
    current_fleet[age_col] = pd.to_numeric(current_fleet[age_col], errors='coerce').fillna(0)
    
    audit_log = []
    yearly_stats = []

    # --- 2. Simulation Loop ---
    for year in range(start_year, max_end_year + 1):
        if year > start_year:
            current_fleet[age_col] += 1
            
        for t in types:
            # Setup dynamic column lookups for this Type
            # Looks for "vehicle count a" or "vehicle count van"
            req_keyword = f"count {t}" if t != 'van' else "count van"
            age_keyword = f"age type {t}"
            
            req_col = [c for c in df_c.columns if req_keyword in c][0]
            max_age_col = [c for c in df_c.columns if age_keyword in c][0]
            loc_col_c = [c for c in df_c.columns if 'location' in c][0]
            loc_col_f = [c for c in df_f.columns if 'location' in c][0]
            type_col_f = [c for c in df_f.columns if 'type' in c][0]
            vin_col_f = [c for c in df_f.columns if 'vin' in c][0]

            # Pool logic
            type_t_fleet = current_fleet[current_fleet[type_col_f].astype(str).str.lower().str.contains(t)].copy()
            pool = []
            assigned_df = pd.DataFrame()

            # Identify Surplus vs Needs
            for _, row in df_c.iterrows():
                loc = row[loc_col_c]
                is_active = (year <= row[end_year_col])
                target = int(row[req_col]) if is_active else 0
                limit = row[max_age_col]
                
                loc_units = type_t_fleet[type_t_fleet[loc_col_f] == loc]
                valid = loc_units[loc_units[age_col] <= limit].sort_values(age_col, ascending=False)
                
                # Keep target, move spares to pool
                if len(valid) > target:
                    keep = valid.head(target)
                    spares = valid.tail(len(valid) - target)
                    assigned_df = pd.concat([assigned_df, keep])
                    pool.append(spares)
                else:
                    assigned_df = pd.concat([assigned_df, valid])
                
                too_old = loc_units[loc_units[age_col] > limit]
                pool.append(too_old)

            pool_df = pd.concat(pool) if pool else pd.DataFrame()

            # Cascading
            for _, row in df_c.iterrows():
                loc = row[loc_col_c]
                limit = row[max_age_col]
                current_count = len(assigned_df[assigned_df[loc_col_f] == loc]) if not assigned_df.empty else 0
                needed = int(row[req_col]) - current_count if year <= row[end_year_col] else 0
                
                if needed > 0 and not pool_df.empty:
                    eligible = pool_df[pool_df[age_col] <= limit].sort_values(age_col)
                    if not eligible.empty:
                        to_move = eligible.head(needed).copy()
                        for idx, move_row in to_move.iterrows():
                            old_loc = move_row[loc_col_f]
                            move_row[loc_col_f] = loc
                            assigned_df = pd.concat([assigned_df, pd.DataFrame([move_row])])
                            pool_df = pool_df.drop(idx)
                            audit_log.append({
                                "Year": year, "VIN": move_row[vin_col_f], "Type": t.upper(),
                                "Action": "CASCADE", "From": old_loc, "To": loc, "Age": move_row[age_col]
                            })

            # Leasing
            for _, row in df_c.iterrows():
                loc = row[loc_col_c]
                target = int(row[req_col]) if year <= row[end_year_col] else 0
                current_count = len(assigned_df[assigned_df[loc_col_f] == loc]) if not assigned_df.empty else 0
                for _ in range(target - current_count):
                    new_vin = f"LSE-{year}-{t.upper()}-{np.random.randint(100,999)}"
                    new_unit = pd.DataFrame([{
                        vin_col_f: new_vin, 'model year': year, age_col: 0, type_col_f: t.upper(), loc_col_f: loc
                    }])
                    assigned_df = pd.concat([assigned_df, new_unit])
                    audit_log.append({"Year": year, "VIN": new_vin, "Type": t.upper(), "Action": "LEASE", "From": "FACTORY", "To": loc, "Age": 0})

            # Update Fleet
            current_fleet = pd.concat([current_fleet[~current_fleet[type_col_f].astype(str).str.lower().str.contains(t)], assigned_df])

        # Stats
        for loc in df_c[loc_col_c].unique():
            loc_data = current_fleet[current_fleet[loc_col_f] == loc]
            yearly_stats.append({
                'Year': year, 'Location': loc, 
                'New Leases': len([a for a in audit_log if a['Year'] == year and a['To'] == loc and a['Action'] == "LEASE"]),
                'Avg Age': round(loc_data[age_col].mean(), 1) if not loc_data.empty else 0
            })

    return pd.DataFrame(audit_log), pd.DataFrame(yearly_stats)

# --- UI ---
st.title("🚛 Fleet Movement & Cascading Waterfall")
uploaded_file = st.file_uploader("Upload Excel", type=["xlsx"])

if uploaded_file:
    try:
        df_c_raw = pd.read_excel(uploaded_file, sheet_name="Contracts")
        df_f_raw = pd.read_excel(uploaded_file, sheet_name="Fleet File")
        
        if st.button("Calculate Waterfall"):
            audit, stats = run_fleet_engine(df_f_raw, df_c_raw)
            
            # SAFE DISPLAY: Only pivot if data exists
            if not stats.empty:
                st.subheader("New Lease Waterfall")
                st.dataframe(stats.pivot_table(index='Location', columns='Year', values='New Leases', aggfunc='sum', fill_value=0))
                
                st.subheader("Maturity Matrix (Avg Age)")
                st.dataframe(stats.pivot_table(index='Location', columns='Year', values='Avg Age', aggfunc='mean', fill_value=0))
                
                st.subheader("Movement Log")
                st.dataframe(audit)
            else:
                st.warning("No data generated. Check your column names.")
                
    except Exception as e:
        st.error(f"Error: {e}")
