import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="Fleet Leasing Optimizer", layout="wide")

st.title("📊 Fleet Leasing & Liquidation Optimizer")
st.markdown("Strategy: Maximize lifespan by cascading Global Assets (Vans) to minimize new lease requirements.")

uploaded_file = st.file_uploader("Upload Excel Fleet Data", type=["xlsx"])

if uploaded_file:
    try:
        df_a = pd.read_excel(uploaded_file, sheet_name=0) 
        df_b = pd.read_excel(uploaded_file, sheet_name=1)

        # 1. Unpivot Requirements (Tab A)
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

        sim_years = st.sidebar.slider("Simulation Horizon (Years)", 5, 10, 7)
        
        if st.sidebar.button("Run Lifecycle Simulation"):
            # Initial Inventory: VINs, Year, Current Age, Type, Location
            inv = df_b.copy().reset_index(drop=True)
            inv['Status'] = 'Active'
            
            lease_requirements = []
            liquidation_log = []

            for year in range(1, sim_years + 1):
                # A. Increment Age
                inv['Current Age'] += 1
                
                # B. Liquidation Phase
                sim_state = inv.merge(reqs_long[['Location', 'Type', 'MaxAge']], on=['Location', 'Type'], how='left')
                liq_mask = sim_state['Current Age'] > sim_state['MaxAge']
                
                if liq_mask.any():
                    liquidated_this_year = inv[liq_mask].copy()
                    liquidated_this_year['Year_Liquidated'] = year
                    liquidation_log.append(liquidated_this_year)
                    # Remove from active fleet
                    inv = inv[~liq_mask].reset_index(drop=True)

                # C. Cascade Phase (Vans Only)
                # We attempt to fill deficits using surplus from other locations
                van_types = ['VAN'] # Logic can be expanded to other types if needed
                for v_type in van_types:
                    for _, r in reqs_long[reqs_long['Type'] == v_type].iterrows():
                        loc, target = r['Location'], r['Target']
                        deficit = target - len(inv[(inv['Location'] == loc) & (inv['Type'] == v_type)])
                        
                        if deficit > 0:
                            # Search for donors
                            for donor_loc in reqs_long[reqs_long['Location'] != loc]['Location'].unique():
                                if deficit <= 0: break
                                d_target = reqs_long[(reqs_long['Location'] == donor_loc) & (reqs_long['Type'] == v_type)]['Target'].values[0]
                                d_vans = inv[(inv['Location'] == donor_loc) & (inv['Type'] == v_type)]
                                surplus = len(d_vans) - d_target
                                
                                if surplus > 0:
                                    move_qty = min(surplus, deficit)
                                    # Move the youngest available surplus to maximize future life at the new location
                                    move_vins = d_vans.sort_values('Current Age').head(move_qty)['VINs'].values
                                    inv.loc[inv['VINs'].isin(move_vins), 'Location'] = loc
                                    deficit -= move_qty

                # D. Calculate Final Leasing Needs for the Year
                for _, r in reqs_long.iterrows():
                    loc, v_type, target = r['Location'], r['Type'], r['Target']
                    final_count = len(inv[(inv['Location'] == loc) & (inv['Type'] == v_type)])
                    needed_to_lease = max(0, int(target - final_count))
                    
                    # Store results
                    lease_requirements.append({
                        'Year': year,
                        'Location': loc,
                        'Vehicle Type': v_type,
                        'Target Count': target,
                        'Active Fleet': final_count,
                        'New Leases Required': needed_to_lease
                    })

            # --- Output Processing ---
            lease_df = pd.DataFrame(lease_requirements)
            all_liq_df = pd.concat(liquidation_log).reset_index(drop=True) if liquidation_log else pd.DataFrame()

            # --- Visualizations ---
            st.subheader("Inventory Waterfall (By Year)")
            
            
            # Pivot for the heatmap/waterfall view
            viz_summary = lease_df.groupby(['Year', 'Location'])['New Leases Required'].sum().reset_index()
            fig = px.bar(viz_summary, x='Year', y='New Leases Required', color='Location', 
                         title="Total New Leases Needed per Year by Location")
            st.plotly_chart(fig, use_container_width=True)

            # --- Key Tables ---
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("📉 Yearly Leasing Requirements")
                st.dataframe(lease_df[lease_df['New Leases Required'] > 0], use_container_width=True)
            
            with col2:
                st.subheader("♻️ Liquidation Audit Trail")
                st.dataframe(all_liq_df[['VINs', 'Type', 'Location', 'Current Age', 'Year_Liquidated']], use_container_width=True)

            # --- Full Download ---
            st.divider()
            st.subheader("📥 Export Simulation Results")
            
            with pd.ExcelWriter("Fleet_Optimization_Results.xlsx") as writer:
                lease_df.to_excel(writer, sheet_name='Lease_Requirements', index=False)
                all_liq_df.to_excel(writer, sheet_name='Liquidation_Audit', index=False)
            
            with open("Fleet_Optimization_Results.xlsx", "rb") as f:
                st.download_button("Download Full Excel Report", f, "Fleet_Optimization_Results.xlsx")

    except Exception as e:
        st.error(f"Logic Error: {e}")
        st.info("Check that your columns match: Location, End Year, Max age type A/C/VAN, Vehicle Count A/C/VAN")
else:
    st.info("Upload the fleet inventory and requirements file to begin.")
