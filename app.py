import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="Fleet Movement Optimizer", layout="wide")

st.title("🚛 Fleet Lifecycle & Movement Tracker")

uploaded_file = st.file_uploader("Upload Excel Fleet Data", type=["xlsx"])

if uploaded_file:
    try:
        df_a = pd.read_excel(uploaded_file, sheet_name=0) 
        df_b = pd.read_excel(uploaded_file, sheet_name=1)

        # 1. Unpivot Tab A (Requirements)
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

        sim_years = st.sidebar.slider("Simulation Horizon", 5, 15, 10)
        
        if st.sidebar.button("Run Simulation & Track Movement"):
            # Initial Inventory: VINs, Year, Current Age, Type, Location
            inv = df_b.copy().reset_index(drop=True)
            
            movement_history = [] # To store the location of every VIN every year
            yearly_metrics = []

            for year in range(1, sim_years + 1):
                # A. Increment Age
                inv['Current Age'] += 1
                
                # B. Handle Liquidation
                sim_state = inv.merge(reqs_long[['Location', 'Type', 'MaxAge']], on=['Location', 'Type'], how='left')
                liquidated_idx = sim_state[sim_state['Current Age'] > sim_state['MaxAge']].index
                
                # Tag liquidated units before they are removed
                inv.loc[liquidated_idx, 'Status'] = 'Liquidated'
                inv.loc[liquidated_idx, 'Liquidation_Year'] = year
                
                # C. Global Asset Redistribution (Vans)
                van_reqs = reqs_long[reqs_long['Type'] == 'VAN']
                for _, r in van_reqs.iterrows():
                    loc, target = r['Location'], r['Target']
                    # Only move active (non-liquidated) vans
                    active_vans = inv[(inv['Location'] == loc) & (inv['Type'] == 'VAN') & (inv['Status'] != 'Liquidated')]
                    deficit = target - len(active_vans)
                    
                    if deficit > 0:
                        for other_loc in reqs_long['Location'].unique():
                            if other_loc == loc or deficit <= 0: continue
                            
                            o_target = reqs_long[(reqs_long['Location'] == other_loc) & (reqs_long['Type'] == 'VAN')]['Target'].values[0]
                            o_vans = inv[(inv['Location'] == other_loc) & (inv['Type'] == 'VAN') & (inv['Status'] != 'Liquidated')]
                            
                            surplus = len(o_vans) - o_target
                            if surplus > 0:
                                move_qty = min(surplus, deficit)
                                move_vins = o_vans.head(move_qty)['VINs'].values
                                inv.loc[inv['VINs'].isin(move_vins), 'Location'] = loc
                                deficit -= move_qty

                # D. Log the State of EVERY VIN for this year
                snapshot = inv.copy()
                snapshot['Simulation_Year'] = year
                movement_history.append(snapshot)

                # E. Cleanup: Remove liquidated units from active pool for the NEXT year
                inv = inv[inv['Status'] != 'Liquidated'].reset_index(drop=True)

            # --- Data Processing ---
            full_history_df = pd.concat(movement_history, ignore_index=True)
            
            # Key Metrics
            total_liq = full_history_df[full_history_df['Status'] == 'Liquidated']['VINs'].nunique()
            st.metric("Total VINs Retired", total_liq)

            # --- Visualizations ---
            st.subheader("Fleet Replacement Waterfall")
            
            
            # Summarize for chart
            summary = full_history_df.groupby(['Simulation_Year', 'Status']).size().reset_index(name='Count')
            fig = px.bar(summary, x='Simulation_Year', y='Count', color='Status', 
                         title="Active vs Liquidated Units Over Time",
                         color_discrete_map={'Liquidated': '#EF553B', 'nan': '#00CC96'})
            st.plotly_chart(fig, use_container_width=True)

            # --- The Master Audit Trail ---
            st.subheader("🔍 Master Audit Trail (Location History)")
            st.markdown("This table shows every VIN's location and age for every year of the simulation.")
            
            # Search Filter
            vin_search = st.text_input("Search by VIN (e.g., see the journey of one vehicle)")
            
            display_df = full_history_df[['VINs', 'Simulation_Year', 'Type', 'Location', 'Current Age', 'Status', 'Liquidation_Year']]
            if vin_search:
                display_df = display_df[display_df['VINs'].astype(str).contains(vin_search)]
            
            st.dataframe(display_df.sort_values(['VINs', 'Simulation_Year']), use_container_width=True)

            # Export
            csv = display_df.to_csv(index=False).encode('utf-8')
            st.download_button("Export Detailed Movement Log (CSV)", csv, "fleet_movement_audit.csv", "text/csv")

    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("Upload the Excel file with the specified column headers to begin.")
