import streamlit as st
import pandas as pd
import plotly.express as px
import io

st.set_page_config(page_title="Fleet Journey Optimizer", layout="wide")

st.title("🚛 Fleet Lifecycle & VIN Journey Tracker")
st.markdown("Simulation Start: **2025** | Simulation End: **Dynamic (from Tab A)**")

uploaded_file = st.file_uploader("Upload Excel Fleet Data", type=["xlsx"])

if uploaded_file:
    try:
        # Load Tabs
        df_a = pd.read_excel(uploaded_file, sheet_name=0) 
        df_b = pd.read_excel(uploaded_file, sheet_name=1)

        # 1. Map Tab A (Requirements)
        # Using 2025 as the anchor, and End Year from the file
        start_year = 2025
        end_year_limit = int(df_a['End Year'].max())
        
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

        if st.sidebar.button("Run Simulation"):
            # Initialize Inventory (Tab B)
            # Ignoring 'Year' from Tab B as requested
            inv = df_b[['VINs', 'Current Age', 'Type', 'Location']].copy().reset_index(drop=True)
            
            journey_records = []
            lease_summary = []
            
            # Log Initial State (Start of 2025)
            start_state = inv.copy()
            start_state['Calendar_Year'] = start_year
            start_state['Event'] = 'Initial Inventory'
            journey_records.append(start_state)

            # 2. Simulation Loop
            for current_year in range(start_year, end_year_limit + 1):
                
                # A. Increment Age (happens at the start of each year)
                if current_year > start_year:
                    inv['Current Age'] += 1
                
                # B. Liquidation Phase
                # Match current fleet against MaxAge rules for their Location/Type
                sim_state = inv.merge(reqs_long[['Location', 'Type', 'MaxAge']], on=['Location', 'Type'], how='left')
                liq_mask = sim_state['Current Age'] > sim_state['MaxAge']
                
                if liq_mask.any():
                    liquidated = inv[liq_mask].copy()
                    liquidated['Calendar_Year'] = current_year
                    liquidated['Event'] = 'LIQUIDATED'
                    journey_records.append(liquidated)
                    
                    inv = inv[~liq_mask].reset_index(drop=True)

                # C. Van Cascade Phase (Global Asset Redistribution)
                # Goal: Move surplus vans to fill deficits before leasing
                van_reqs = reqs_long[reqs_long['Type'] == 'VAN']
                for _, r in van_reqs.iterrows():
                    loc, target = r['Location'], r['Target']
                    current_vans = inv[(inv['Location'] == loc) & (inv['Type'] == 'VAN')]
                    deficit = target - len(current_vans)
                    
                    if deficit > 0:
                        for donor_loc in reqs_long['Location'].unique():
                            if donor_loc == loc or deficit <= 0: continue
                            
                            d_target = reqs_long[(reqs_long['Location'] == donor_loc) & (reqs_long['Type'] == 'VAN')]['Target'].values[0]
                            d_vans = inv[(inv['Location'] == donor_loc) & (inv['Type'] == 'VAN')]
                            surplus = len(d_vans) - d_target
                            
                            if surplus > 0:
                                move_qty = min(surplus, deficit)
                                # Sort by Current Age to move the most useful assets
                                move_vins = d_vans.sort_values('Current Age').head(move_qty)['VINs'].values
                                
                                # Log Move Event
                                moves_log = inv[inv['VINs'].isin(move_vins)].copy()
                                moves_log['Calendar_Year'] = current_year
                                moves_log['Event'] = f'MOVED (From {donor_loc} to {loc})'
                                journey_records.append(moves_log)
                                
                                # Update Inventory Location
                                inv.loc[inv['VINs'].isin(move_vins), 'Location'] = loc
                                deficit -= move_qty

                # D. Record Lease Requirements for this Year
                for _, r in reqs_long.iterrows():
                    l, t, target = r['Location'], r['Type'], r['Target']
                    actual_count = len(inv[(inv['Location'] == l) & (inv['Type'] == t)])
                    needed = max(0, int(target - actual_count))
                    
                    lease_summary.append({
                        'Calendar_Year': current_year,
                        'Location': l,
                        'Type': t,
                        'Target_Count': target,
                        'Actual_Count': actual_count,
                        'New_Leases_Required': needed
                    })
                
                # Log active fleet state for the end of the year
                active_log = inv.copy()
                active_log['Calendar_Year'] = current_year
                active_log['Event'] = 'Active'
                journey_records.append(active_log)

            # --- Results Processing ---
            full_journey_df = pd.concat(journey_records, ignore_index=True)
            full_journey_df = full_journey_df.sort_values(['VINs', 'Calendar_Year', 'Event'])
            
            lease_df = pd.DataFrame(lease_summary)
            # Calculate totals
            total_leases = lease_df['New_Leases_Required'].sum()
            total_liquidated = full_journey_df[full_journey_df['Event'] == 'LIQUIDATED']['VINs'].nunique()
            
            # Top Level Metrics
            col1, col2, col3 = st.columns(3)
            col1.metric("Total Leases Triggered", f"{total_leases} units")
            col2.metric("Total Units Liquidated", f"{total_liquidated} units")
            col3.metric("Leases Avoided (via Cascading)", "Calculated") # Optional logic to show savings
            # --- Visual Dashboard ---
            st.subheader("Yearly Lease Waterfall")
            
            
            fig = px.bar(lease_df[lease_df['New_Leases_Required'] > 0], 
                         x='Calendar_Year', y='New_Leases_Required', color='Location',
                         title="New Leases Needed (Post-Cascade Optimization)")
            st.plotly_chart(fig, use_container_width=True)

            # --- Searchable Audit Trail ---
            st.subheader("🔍 Individual VIN Journey")
            vin_query = st.text_input("Search VIN to see its location history and life events")
            if vin_query:
                st.dataframe(full_journey_df[full_journey_df['VINs'].astype(str).contains(vin_query)], use_container_width=True)
            else:
                st.info("Showing first 50 records. Search a VIN above for a specific journey.")
                st.dataframe(full_journey_df.head(50), use_container_width=True)

            # --- Export ---
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                lease_df.to_excel(writer, sheet_name='Lease Requirements', index=False)
                full_journey_df.to_excel(writer, sheet_name='VIN Journey Audit', index=False)
            
            st.download_button(
                label="📥 Download Optimization Report (Excel)",
                data=output.getvalue(),
                file_name="Fleet_Strategy_Report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    except Exception as e:
        st.error(f"Error in Simulation: {e}")
else:
    st.info("Please upload the file. Simulation will start in 2025 and run until the End Year in Tab A.")
