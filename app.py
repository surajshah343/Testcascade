import streamlit as st
import pandas as pd
import plotly.express as px
import io

st.set_page_config(page_title="Global Fleet Shuffle Optimizer", layout="wide")

st.title("🚌 Global Fleet Shuffle & Lease Minimizer")
st.markdown("Optimization Engine: **Shuffle Surplus First, Lease Last.**")

uploaded_file = st.file_uploader("Upload Excel Fleet Data", type=["xlsx"])

if uploaded_file:
    try:
        df_a = pd.read_excel(uploaded_file, sheet_name=0) 
        df_b = pd.read_excel(uploaded_file, sheet_name=1)

        # Use 2025 as anchor, End Year from Tab A
        start_year = 2025
        end_year_limit = int(df_a['End Year'].max())
        
        # Unpivot Tab A (Requirements) for processing
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

        if st.sidebar.button("Run Global Shuffle Simulation"):
            # Setup Inventory from Tab B
            inv = df_b[['VINs', 'Current Age', 'Type', 'Location']].copy().reset_index(drop=True)
            
            journey_records = []
            lease_summary = []
            
            # Year 0 Baseline
            start_state = inv.copy()
            start_state['Calendar_Year'] = start_year
            start_state['Event'] = 'Initial Inventory'
            journey_records.append(start_state)

            for current_year in range(start_year, end_year_limit + 1):
                # A. Aging (Age increases every Jan 1st after 2025)
                if current_year > start_year:
                    inv['Current Age'] += 1
                
                # B. Liquidation
                sim_state = inv.merge(reqs_long[['Location', 'Type', 'MaxAge']], on=['Location', 'Type'], how='left')
                liq_mask = sim_state['Current Age'] > sim_state['MaxAge']
                
                if liq_mask.any():
                    liquidated = inv[liq_mask].copy()
                    liquidated['Calendar_Year'] = current_year
                    liquidated['Event'] = 'LIQUIDATED'
                    journey_records.append(liquidated)
                    inv = inv[~liq_mask].reset_index(drop=True)

                # C. The Global Shuffle (Minimize Leased Units)
                for v_type in ['A', 'C', 'VAN']:
                    # Find locations with a deficit
                    for _, r in reqs_long[reqs_long['Type'] == v_type].iterrows():
                        loc, target = r['Location'], r['Target']
                        deficit = target - len(inv[(inv['Location'] == loc) & (inv['Type'] == v_type)])
                        
                        if deficit > 0:
                            # Search the network for surplus
                            for donor_loc in reqs_long['Location'].unique():
                                if donor_loc == loc or deficit <= 0: continue
                                
                                d_target = reqs_long[(reqs_long['Location'] == donor_loc) & (reqs_long['Type'] == v_type)]['Target'].values[0]
                                d_units = inv[(inv['Location'] == donor_loc) & (inv['Type'] == v_type)]
                                surplus = len(d_units) - d_target
                                
                                if surplus > 0:
                                    move_qty = min(surplus, deficit)
                                    # Pick youngest surplus units to maximize future service
                                    move_vins = d_units.sort_values('Current Age').head(move_qty)['VINs'].values
                                    
                                    # Log Transfer
                                    moves_log = inv[inv['VINs'].isin(move_vins)].copy()
                                    moves_log['Calendar_Year'] = current_year
                                    moves_log['Event'] = f'SHUFFLED (to {loc} from {donor_loc})'
                                    journey_records.append(moves_log)
                                    
                                    # Update Inventory
                                    inv.loc[inv['VINs'].isin(move_vins), 'Location'] = loc
                                    deficit -= move_qty

                # D. Calculate Final Lease Needs
                for _, r in reqs_long.iterrows():
                    l, t, target = r['Location'], r['Type'], r['Target']
                    final_count = len(inv[(inv['Location'] == l) & (inv['Type'] == t)])
                    needed = max(0, int(target - final_count))
                    
                    lease_summary.append({
                        'Calendar_Year': current_year,
                        'Location': l,
                        'Type': t,
                        'New_Leases_Required': needed
                    })
                
                # Log End-of-Year State
                active_log = inv.copy()
                active_log['Calendar_Year'] = current_year
                active_log['Event'] = 'Active'
                journey_records.append(active_log)

            # --- Presentation & Export ---
            full_journey_df = pd.concat(journey_records, ignore_index=True).sort_values(['VINs', 'Calendar_Year'])
            lease_df = pd.DataFrame(lease_summary)

            # Chart
            st.subheader("New Leases Required Over Time")
            fig = px.bar(lease_df[lease_df['New_Leases_Required'] > 0], x='Calendar_Year', y='New_Leases_Required', color='Location', barmode='group')
            st.plotly_chart(fig, use_container_width=True)

            # Audit
            st.subheader("🔍 Master VIN Journey (Movement History)")
            st.dataframe(full_journey_df.head(100), use_container_width=True)

            # Export
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                lease_df.to_excel(writer, sheet_name='Lease Requirements', index=False)
                full_journey_df.to_excel(writer, sheet_name='VIN Journey Audit', index=False)
            
            st.download_button("📥 Download Optimization Report (Excel)", output.getvalue(), "Fleet_Shuffle_Report.xlsx")

    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("Upload your fleet file to begin. Simulation will run 2025 to End Year.")
