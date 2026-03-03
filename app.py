import streamlit as st
import pandas as pd
import plotly.express as px
import io

st.set_page_config(page_title="Global Fleet Rescue Optimizer", layout="wide")

st.title("🚌 Fleet Rescue & Lease Minimizer")
st.markdown("""
**Optimization Strategy:**
1. **Identify Homeless:** Vehicles that exceed their *current* location's Max Age are placed in a Rescue Pool.
2. **Rescue & Relocate:** The system attempts to move these Homeless units to other locations that have a higher Max Age allowance and a deficit.
3. **Lease:** Only triggered if the Rescue Pool and Surplus units cannot fill a local deficit.
""")

uploaded_file = st.file_uploader("Upload Excel Fleet Data", type=["xlsx"])

if uploaded_file:
    try:
        df_a = pd.read_excel(uploaded_file, sheet_name=0) 
        df_b = pd.read_excel(uploaded_file, sheet_name=1)

        start_year = 2025
        end_year_limit = int(df_a['End Year'].max())
        
        # Unpivot Tab A
        mapping = [
            {'Type': 'A', 'MaxAge': 'Max age type A', 'Target': 'Vehicle Count A'},
            {'Type': 'C', 'MaxAge': 'Max age type C', 'Target': 'Vehicle Count C'},
            {'Type': 'VAN', 'MaxAge': 'Max age type VAN', 'Target': 'Vehicle Count Van'}
        ]
        
        req_list = []
        for item in mapping:
            temp = df_a[['Location', 'End Year', item['MaxAge'], item['Target']]].copy()
            temp['Type'] = item['Type']
            temp = temp.rename(columns={item['MaxAge']: 'MaxAge', item['Target']: 'Target', 'End Year': 'EndYear'})
            req_list.append(temp)
        reqs_long = pd.concat(req_list, ignore_index=True)

        if st.sidebar.button("Run Rescue Simulation"):
            inv = df_b[['VINs', 'Current Age', 'Type', 'Location']].copy().reset_index(drop=True)
            journey_records = []
            lease_summary = []
            
            # Initial State Log
            start_state = inv.copy()
            start_state['Calendar_Year'] = start_year
            start_state['Event'] = 'Initial Inventory'
            journey_records.append(start_state)

            for current_year in range(start_year, end_year_limit + 1):
                if current_year > start_year:
                    inv['Current Age'] += 1
                
                # --- A. Identify Homeless Vehicles ---
                # Check against the MaxAge of their CURRENT location
                sim_state = inv.merge(reqs_long[['Location', 'Type', 'MaxAge']], on=['Location', 'Type'], how='left')
                invalid_mask = sim_state['Current Age'] > sim_state['MaxAge']
                
                homeless_pool = inv[invalid_mask].copy()
                homeless_pool['Source'] = 'Homeless'
                
                # Keep only valid units in active inventory for now
                inv = inv[~invalid_mask].reset_index(drop=True)

                # --- B. Identify Surplus Vehicles ---
                surplus_pool_list = []
                for v_type in ['A', 'C', 'VAN']:
                    for _, r in reqs_long[reqs_long['Type'] == v_type].iterrows():
                        loc, target = r['Location'], r['Target']
                        current_units = inv[(inv['Location'] == loc) & (inv['Type'] == v_type)]
                        surplus_count = len(current_units) - target
                        
                        if surplus_count > 0:
                            # Pull the youngest surplus units into the pool
                            surplus_vins = current_units.sort_values('Current Age').head(surplus_count).copy()
                            surplus_vins['Source'] = 'Surplus'
                            surplus_pool_list.append(surplus_vins)
                            # Remove them from active inventory so they can be redistributed
                            inv = inv[~inv['VINs'].isin(surplus_vins['VINs'])]

                # Combine Homeless and Surplus into one Master Pool
                available_pool = pd.concat([homeless_pool] + surplus_pool_list, ignore_index=True) if surplus_pool_list or not homeless_pool.empty else pd.DataFrame(columns=inv.columns.tolist() + ['Source'])

                # --- C. Rescue & Relocate Phase ---
                for v_type in ['A', 'C', 'VAN']:
                    type_reqs = reqs_long[reqs_long['Type'] == v_type]
                    for _, r in type_reqs.iterrows():
                        loc, target, max_age = r['Location'], r['Target'], r['MaxAge']
                        current_valid = len(inv[(inv['Location'] == loc) & (inv['Type'] == v_type)])
                        deficit = target - current_valid
                        
                        if deficit > 0 and not available_pool.empty:
                            # Find units in the pool that are legally allowed to operate at this location
                            valid_in_pool = available_pool[(available_pool['Type'] == v_type) & (available_pool['Current Age'] <= max_age)].copy()
                            
                            if not valid_in_pool.empty:
                                # Prioritize saving "Homeless" units first to prevent liquidation
                                valid_in_pool['Priority'] = valid_in_pool['Source'].apply(lambda x: 0 if x == 'Homeless' else 1)
                                to_move = valid_in_pool.sort_values(['Priority', 'Current Age']).head(deficit)
                                
                                for _, unit in to_move.iterrows():
                                    v_id = unit['VINs']
                                    original_loc = unit['Location']
                                    
                                    # Update and return to active inventory
                                    new_row = unit.drop(['Source', 'Priority'])
                                    new_row['Location'] = loc
                                    inv = pd.concat([inv, pd.DataFrame([new_row])], ignore_index=True)
                                    
                                    # Log the rescue/move
                                    log = new_row.copy()
                                    log['Calendar_Year'] = current_year
                                    log['Event'] = 'RESCUED (Saved from Liquidation)' if unit['Source'] == 'Homeless' else f'SHUFFLED (From {original_loc})'
                                    journey_records.append(log)
                                    
                                    # Remove from available pool
                                    available_pool = available_pool[available_pool['VINs'] != v_id]
                                    deficit -= 1

                # --- D. Final Cleanup & Lease Calculation ---
                # Any Homeless units left in the pool that couldn't find a valid location are officially liquidated
                if not available_pool.empty:
                    liquidated = available_pool[available_pool['Source'] == 'Homeless']
                    for _, unit in liquidated.iterrows():
                        log = unit.drop(['Source']).copy()
                        log['Calendar_Year'] = current_year
                        log['Event'] = 'LIQUIDATED (No valid location found)'
                        journey_records.append(log)
                    
                    # Any Surplus units left just return to their original location
                    leftovers = available_pool[available_pool['Source'] == 'Surplus'].drop(columns=['Source'])
                    if not leftovers.empty:
                        inv = pd.concat([inv, leftovers], ignore_index=True)

                # Record final leases needed
                for _, r in reqs_long.iterrows():
                    l, t, target = r['Location'], r['Type'], r['Target']
                    final_count = len(inv[(inv['Location'] == l) & (inv['Type'] == t)])
                    needed = max(0, int(target - final_count))
                    
                    lease_summary.append({
                        'Calendar_Year': current_year,
                        'Location': l,
                        'Type': t,
                        'Active_Fleet': final_count,
                        'New_Leases_Required': needed
                    })
                
                # Log Active State
                active_log = inv.copy()
                active_log['Calendar_Year'] = current_year
                active_log['Event'] = 'Active'
                journey_records.append(active_log)

            # --- Output & Export ---
            full_journey_df = pd.concat(journey_records, ignore_index=True).sort_values(['VINs', 'Calendar_Year'])
            lease_df = pd.DataFrame(lease_summary)

            st.subheader("Global New Leases Required Over Time")
            fig = px.bar(lease_df[lease_df['New_Leases_Required'] > 0], x='Calendar_Year', y='New_Leases_Required', color='Location')
            st.plotly_chart(fig, use_container_width=True)

            st.subheader("🔍 Master VIN Journey (Watch the Rescues)")
            st.markdown("Search a VIN to see if it was **RESCUED** and moved to a 'Spare' location to avoid liquidation.")
            st.dataframe(full_journey_df.head(100), use_container_width=True)

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                lease_df.to_excel(writer, sheet_name='Lease Requirements', index=False)
                full_journey_df.to_excel(writer, sheet_name='VIN Journey Audit', index=False)
            
            st.download_button("📥 Download Rescue & Relocation Report", output.getvalue(), "Fleet_Rescue_Report.xlsx")

    except Exception as e:
        st.error(f"Error: {e}")
