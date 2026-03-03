import streamlit as st
import pandas as pd
import plotly.express as px
import io

st.set_page_config(page_title="Fleet Journey Optimizer", layout="wide")

st.title("🚛 Fleet Lifecycle & VIN Journey Tracker")
st.markdown("This simulation minimizes leases by cascading assets and tracks the **full location history** for every VIN.")

uploaded_file = st.file_uploader("Upload Fleet Excel File", type=["xlsx"])

if uploaded_file:
    try:
        df_a = pd.read_excel(uploaded_file, sheet_name=0) 
        df_b = pd.read_excel(uploaded_file, sheet_name=1)

        # 1. Unpivot Requirements (Tab A) using exact columns provided
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

        sim_years = st.sidebar.slider("Simulation Years", 1, 15, 10)
        
        if st.sidebar.button("Run Simulation & Generate Journey Log"):
            # Initialize Inventory and History
            inv = df_b.copy().reset_index(drop=True)
            
            # Start the journey log with initial state
            journey_log = inv.copy()
            journey_log['Year'] = 0
            journey_log['Event'] = 'Initial Inventory'
            
            lease_summary = []
            
            # Active tracking list
            journey_records = [journey_log]

            for year in range(1, sim_years + 1):
                # A. Aging
                inv['Current Age'] += 1
                
                # B. Liquidation
                sim_state = inv.merge(reqs_long[['Location', 'Type', 'MaxAge']], on=['Location', 'Type'], how='left')
                liq_mask = sim_state['Current Age'] > sim_state['MaxAge']
                
                if liq_mask.any():
                    liquidated_vins = inv[liq_mask].copy()
                    liquidated_vins['Year'] = year
                    liquidated_vins['Event'] = 'LIQUIDATED (Age Limit)'
                    journey_records.append(liquidated_vins)
                    
                    inv = inv[~liq_mask].reset_index(drop=True)

                # C. Cascade Logic (Vans)
                for _, r in reqs_long[reqs_long['Type'] == 'VAN'].iterrows():
                    loc, target = r['Location'], r['Target']
                    current_count = len(inv[(inv['Location'] == loc) & (inv['Type'] == 'VAN')])
                    deficit = target - current_count
                    
                    if deficit > 0:
                        # Find Surplus Donors
                        for donor_loc in reqs_long[reqs_long['Location'] != loc]['Location'].unique():
                            if deficit <= 0: break
                            
                            d_target = reqs_long[(reqs_long['Location'] == donor_loc) & (reqs_long['Type'] == 'VAN')]['Target'].values[0]
                            d_vans = inv[(inv['Location'] == donor_loc) & (inv['Type'] == 'VAN')]
                            surplus = len(d_vans) - d_target
                            
                            if surplus > 0:
                                move_qty = min(surplus, deficit)
                                move_vins = d_vans.sort_values('Current Age').head(move_qty)['VINs'].values
                                
                                # Log the movement
                                moved_units = inv[inv['VINs'].isin(move_vins)].copy()
                                moved_units['Location'] = loc # Update location in log
                                moved_units['Year'] = year
                                moved_units['Event'] = f'CASCADED (From {donor_loc})'
                                journey_records.append(moved_units)
                                
                                # Update actual inventory
                                inv.loc[inv['VINs'].isin(move_vins), 'Location'] = loc
                                deficit -= move_qty

                # D. Calculate Leasing Needs
                for _, r in reqs_long.iterrows():
                    loc, v_type, target = r['Location'], r['Type'], r['Target']
                    final_count = len(inv[(inv['Location'] == loc) & (inv['Type'] == v_type)])
                    leases_needed = max(0, int(target - final_count))
                    
                    lease_summary.append({
                        'Year': year,
                        'Location': loc,
                        'Type': v_type,
                        'Leases_Needed': leases_needed,
                        'Fleet_Count': final_count
                    })

            # --- Finalize Output ---
            master_journey = pd.concat(journey_records, ignore_index=True).sort_values(['VINs', 'Year'])
            lease_df = pd.DataFrame(lease_summary)

            # --- Visualizations ---
            st.subheader("Total Leasing Requirements by Year")
            
            
            fig = px.bar(lease_df[lease_df['Leases_Needed'] > 0], x='Year', y='Leases_Needed', color='Location',
                         title="Required New Leases (Post-Cascade Optimization)")
            st.plotly_chart(fig, use_container_width=True)

            # --- UI Display ---
            col1, col2 = st.columns([1, 2])
            with col1:
                st.subheader("Summary Table")
                st.dataframe(lease_df[lease_df['Leases_Needed'] > 0], use_container_width=True)
            
            with col2:
                st.subheader("VIN Journey Audit Trail")
                search_vin = st.text_input("Filter Journey by VIN")
                if search_vin:
                    st.dataframe(master_journey[master_journey['VINs'].astype(str).contains(search_vin)], use_container_width=True)
                else:
                    st.dataframe(master_journey.head(100), use_container_width=True)

            # --- Excel Export Logic ---
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                lease_df.to_excel(writer, sheet_name='Lease Requirements', index=False)
                master_journey.to_excel(writer, sheet_name='VIN Journey Audit', index=False)
                
            st.download_button(
                label="📥 Download Optimization Report (Excel)",
                data=buffer.getvalue(),
                file_name="Fleet_Optimization_Report.xlsx",
                mime="application/vnd.ms-excel"
            )

    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("Upload your Excel file to generate the multi-year cascade and leasing report.")
