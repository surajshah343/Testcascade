import streamlit as st
import pandas as pd
import plotly.express as px
import io

st.set_page_config(page_title="Global Fleet Shuffle Optimizer", layout="wide")

st.title("🚌 Global Fleet Shuffle & Lease Minimizer")
st.markdown("""
**Optimization Strategy:** Treats all Locations as a single network. 
1. **Liquidate** units exceeding Max Age.
2. **Shuffle** surplus units across locations by Type (A to A, C to C, Van to Van).
3. **Lease** only when the global network cannot fulfill a local deficit.
""")

uploaded_file = st.file_uploader("Upload Excel Fleet Data", type=["xlsx"])

if uploaded_file:
    try:
        df_a = pd.read_excel(uploaded_file, sheet_name=0) 
        df_b = pd.read_excel(uploaded_file, sheet_name=1)

        # 1. Timeline and Mapping
        start_year = 2025
        end_year_limit = int(df_a['End Year'].max())
        
        # Unpivot Tab A to a searchable format
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
            # Initial Inventory (Tab B)
            inv = df_b[['VINs', 'Current Age', 'Type', 'Location']].copy().reset_index(drop=True)
            
            journey_records = []
            lease_summary = []
            
            # Record Initial State
            start_state = inv.copy()
            start_state['Calendar_Year'] = start_year
            start_state['Event'] = 'Initial Inventory'
            journey_records.append(start_state)

            # 2. Year-by-Year Simulation
            for current_year in range(start_year, end_year_limit + 1):
                # A. Aging (starts from second year of simulation)
                if current_year > start_year:
                    inv['Current Age'] += 1
                
                # B. LIQUIDATION PHASE
                # Dynamic matching against Max Age constraints
                sim_state = inv.merge(reqs_long[['Location', 'Type', 'MaxAge']], on=['Location', 'Type'], how='left')
                liq_mask = sim_state['Current Age'] > sim_state['MaxAge']
                
                if liq_mask.any():
                    liquidated = inv[liq_mask].copy()
                    liquidated['Calendar_Year'] = current_year
                    liquidated['Event'] = 'LIQUIDATED (Max Age Exceeded)'
                    journey_records.append(liquidated)
                    # Remove from active inventory
                    inv = inv[~liq_mask].reset_index(drop=True)

                # C. GLOBAL SHUFFLE PHASE (Relocation)
                # We iterate by Type to ensure A fills A, C fills C, etc.
                for v_type in ['A', 'C', 'VAN']:
                    type_reqs = reqs_long[reqs_long['Type'] == v_type]
                    
                    for _, r in type_reqs.iterrows():
                        loc, target = r['Location'], r['Target']
                        current_units = inv[(inv['Location'] == loc) & (inv['Type'] == v_type)]
                        deficit = target - len(current_units)
                        
                        if deficit > 0:
                            # Search the whole network for surplus of the same type
                            for donor_loc in reqs_long['Location'].unique():
                                if donor_loc == loc or deficit <= 0: continue
                                
                                d_target = reqs_long[(reqs_long['Location'] == donor_loc) & (reqs_long['Type'] == v_type)]['Target'].values[0]
                                d_units = inv[(inv['Location'] == donor_loc) & (inv['Type'] == v_type)]
                                surplus = len(d_units) - d_target
                                
                                if surplus > 0:
                                    move_qty = min(surplus, deficit)
                                    # Pick youngest surplus units to relocate (maximizes future life)
                                    move_vins = d_units.sort_values('Current Age').head(move_qty)['VINs'].values
                                    
                                    # Log Transfer
                                    moves_log = inv[inv['VINs'].isin(move_vins)].copy()
                                    moves_log['Calendar_Year'] = current_year
                                    moves_log['Event'] = f'SHUFFLED (From {donor_loc} to {loc})'
                                    journey_records.append(moves_log)
                                    
                                    # Update Inventory Location
                                    inv.loc[inv['VINs'].isin(move_vins), 'Location'] = loc
                                    deficit -= move_qty

                # D. LEASE RECORDING
                # Check final counts at each location after shuffling
                for _, r in reqs_long.iterrows():
                    l, t, target = r['Location'], r['Type'], r['Target']
                    final_count = len(inv[(inv['Location'] == l) & (inv['Type'] == t)])
                    needed = max(0, int(target - final_count))
                    
                    lease_summary.append({
                        'Calendar_Year': current_year,
                        'Location': l,
                        'Type': t,
                        'Leases_Needed': needed
                    })
                
                # Log Active State
                active_log = inv.copy()
                active_log['Calendar_Year'] = current_year
                active_log['Event'] = 'Active'
                journey_records.append(active_log)

            # --- Presentation Layer ---
            full_journey_df = pd.concat(journey_records, ignore_index=True).sort_values(['VINs', 'Calendar_Year'])
            lease_df = pd.DataFrame(lease_summary)

            # Metrics
            st.divider()
            m1, m2, m3 = st.columns(3)
            m1.metric("Total New Leases", lease_df['Leases_Needed'].sum())
            m2.metric("Total Liquidations", full_journey_df[full_journey_df['Event'].str.contains('LIQUIDATED')]['VINs'].nunique())
            m3.metric("Shuffle Events", full_journey_df[full_journey_df['Event'].str.contains('SHUFFLED')]['VINs'].count())

            # Waterfall Chart
            st.subheader("Year-over-Year Leasing Requirements")
            
            fig = px.bar(lease_df[lease_df['Leases_Needed'] > 0], x='Calendar_Year', y='Leases_Needed', color='Location', barmode='group')
            st.plotly_chart(fig, use_container_width=True)

            # Audit Trail
            st.subheader("🔍 Individual VIN Lifecycle & Shuffle History")
            search_vin = st.text_input("Search VIN to see its location changes and retirement year")
            if search_vin:
                st.dataframe(full_journey_df[full_journey_df['VINs'].astype(str).contains(search_vin)], use_container_width=True)
            else:
                st.dataframe(full_journey_df.head(100), use_container_width=True)

            # Export
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                lease_df.to_excel(writer, sheet_name='Lease Requirements', index=False)
                full_journey_df.to_excel(writer, sheet_name='VIN Journey Audit', index=False)
            
            st.download_button("📥 Download Optimization Report (Excel)", output.getvalue(), "Global_Shuffle_Report.xlsx")

    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.info("Upload your Excel file to start the 2025-{} simulation.".format("End Year"))
