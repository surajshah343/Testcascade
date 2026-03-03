import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="Fleet Optimizer", layout="wide")

st.title("🚛 Fleet Management & Leasing Optimizer")

uploaded_file = st.file_uploader("Upload Excel Fleet Data", type=["xlsx"])

if uploaded_file:
    try:
        # Load exactly as specified
        df_a = pd.read_excel(uploaded_file, sheet_name=0) # Tab A
        df_b = pd.read_excel(uploaded_file, sheet_name=1) # Tab B

        # 1. Transform Tab A from Wide to Long (Unpivot)
        # Mapping the exact column names provided
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

        # 2. Simulation Parameters
        sim_years = st.sidebar.slider("Simulation Years", 5, 10, 7)
        
        if st.sidebar.button("Run Simulation"):
            # Prepare Inventory from Tab B: VINs, Year, Current Age, Type, Location
            # We use .copy() and reset_index to prevent alignment errors
            inv = df_b.copy().reset_index(drop=True)
            
            audit_trail = []
            viz_data = []

            for year in range(1, sim_years + 1):
                # A. Increment Age
                inv['Current Age'] += 1
                
                # B. Handle Liquidation (The "Unalignable" Fix)
                # We merge rules onto the inventory to find who exceeds MaxAge
                sim_state = inv.merge(reqs_long[['Location', 'Type', 'MaxAge']], on=['Location', 'Type'], how='left')
                
                # Identify liquidated rows
                liquidated_idx = sim_state[sim_state['Current Age'] > sim_state['MaxAge']].index
                
                if not liquidated_idx.empty:
                    liquidated_units = inv.loc[liquidated_idx].copy()
                    liquidated_units['Year_of_Liquidation'] = year
                    liquidated_units['Status'] = 'Liquidated'
                    audit_trail.append(liquidated_units)
                    
                    # Remove from active inventory and reset index to keep it clean for next year
                    inv = inv.drop(liquidated_idx).reset_index(drop=True)

                # C. Global Asset Logic (Vans)
                # Check for Van deficits vs surpluses
                van_reqs = reqs_long[reqs_long['Type'] == 'VAN']
                for _, r in van_reqs.iterrows():
                    loc, target = r['Location'], r['Target']
                    current_vans = inv[(inv['Location'] == loc) & (inv['Type'] == 'VAN')]
                    deficit = target - len(current_vans)
                    
                    if deficit > 0:
                        # Find potential donors (Vans at other locations where count > target)
                        for other_loc in reqs_long['Location'].unique():
                            if other_loc == loc or deficit <= 0: continue
                            
                            o_target = reqs_long[(reqs_long['Location'] == other_loc) & (reqs_long['Type'] == 'VAN')]['Target'].values[0]
                            o_vans = inv[(inv['Location'] == other_loc) & (inv['Type'] == 'VAN')]
                            
                            surplus = len(o_vans) - o_target
                            if surplus > 0:
                                move_qty = min(surplus, deficit)
                                move_vins = o_vans.head(move_qty)['VINs'].values
                                inv.loc[inv['VINs'].isin(move_vins), 'Location'] = loc
                                deficit -= move_qty
                
                # D. Record Yearly Metrics (Leased vs Liquidated)
                for _, r in reqs_long.iterrows():
                    loc, v_type, target = r['Location'], r['Type'], r['Target']
                    actual_count = len(inv[(inv['Location'] == loc) & (inv['Type'] == v_type)])
                    
                    needed_to_lease = max(0, target - actual_count)
                    
                    # Count liquidations for this specific location/type this year
                    liq_count = 0
                    if not liquidated_idx.empty:
                        liq_count = len(liquidated_units[(liquidated_units['Location'] == loc) & (liquidated_units['Type'] == v_type)])

                    viz_data.append({
                        'Year': year,
                        'Location': loc,
                        'Type': v_type,
                        'Leased': needed_to_lease,
                        'Liquidated': liq_count
                    })

            # --- Results UI ---
            res_df = pd.DataFrame(viz_data)
            full_audit = pd.concat(audit_trail) if audit_trail else pd.DataFrame()

            # Key Metric Cards
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Liquidated", len(full_audit))
            c2.metric("Total New Leases", res_df['Leased'].sum())
            c3.metric("Final Active Fleet", len(inv))

            # Waterfall Timeline (Stacked Bar)
            st.subheader("Leasing vs Liquidation Waterfall")
            
            
            # Grouping by Year and Status for the chart
            chart_df = res_df.groupby('Year')[['Leased', 'Liquidated']].sum().reset_index()
            fig = px.bar(chart_df, x='Year', y=['Leased', 'Liquidated'], 
                         title="Annual Fleet Replacement Requirements",
                         color_discrete_map={"Leased": "#EF553B", "Liquidated": "#636EFA"},
                         barmode='group')
            st.plotly_chart(fig, use_container_width=True)

            # Audit Trail
            st.subheader("🔍 Searchable Audit Trail")
            st.dataframe(full_audit, use_container_width=True)

            # CSV Download
            if not full_audit.empty:
                csv = full_audit.to_csv(index=False).encode('utf-8')
                st.download_button("Download Audit Results", csv, "fleet_audit.csv", "text/csv")

    except Exception as e:
        st.error(f"Simulation Error: {e}")
        st.info("Ensure Tab A has: Location, End Year, Max age type A, Max age type C, Max age type VAN, Vehicle Count A, Vehicle Count C, Vehicle Count Van")

else:
    st.warning("Please upload the Fleet Excel file to begin.")
