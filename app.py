import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="Fleet Cascade Optimizer", layout="wide")

## --- UI Header ---
st.title("🚌 Multi-Type Fleet Lifecycle Optimizer")
st.markdown("Automated leasing and liquidation simulation based on location-specific age constraints.")

uploaded_file = st.file_uploader("Upload Excel Fleet Data (Tab A: Reqs, Tab B: Inv)", type=["xlsx"])

if uploaded_file:
    try:
        # Load Raw Data
        df_a = pd.read_excel(uploaded_file, sheet_name=0)
        df_b = pd.read_excel(uploaded_file, sheet_name=1)

        ## --- Pre-processing Tab A (The Wide-to-Long Melt) ---
        # We need to transform Type A, Type C, and Van columns into a unified 'Type' column
        # Logic: Identify Max Age columns and Count columns
        
        age_cols = {
            'A': 'Max age type A',
            'C': 'Max age type C',
            'VAN': 'Max age type VAN'
        }
        count_cols = {
            'A': 'Vehicle Count A',
            'C': 'Vehicle Count C',
            'VAN': 'Vehicle Count Van'
        }

        # Create a cleaned Requirements table
        req_list = []
        for vehicle_type in ['A', 'C', 'VAN']:
            temp_df = df_a[['Location', 'End Year', age_cols[vehicle_type], count_cols[vehicle_type]]].copy()
            temp_df['Type'] = vehicle_type
            temp_df.columns = ['Location', 'EndYear', 'MaxAge', 'Target', 'Type']
            req_list.append(temp_df)
        
        reqs_cleaned = pd.concat(req_list, ignore_index=True)

        ## --- Simulation Engine ---
        sim_years = st.sidebar.slider("Simulation Horizon (Years)", 1, 15, 10)
        
        if st.sidebar.button("Run Fleet Simulation"):
            # Initial Inventory State
            # Columns: VINs, Year, Current Age, Type, Location
            inv = df_b.copy()
            inv.columns = ['VIN', 'Year_Model', 'Age', 'Type', 'Location']
            
            audit_trail = []
            yearly_summary = []

            for y in range(1, sim_years + 1):
                # 1. Aging
                inv['Age'] += 1
                
                # 2. Identify Liquidations
                # Match inventory to the MaxAge rules in reqs_cleaned
                merged = inv.merge(reqs_cleaned[['Location', 'Type', 'MaxAge']], on=['Location', 'Type'], how='left')
                
                liquidated_mask = merged['Age'] > merged['MaxAge']
                liquidated_units = inv[liquidated_mask].copy()
                liquidated_units['Year_of_Liquidation'] = y
                liquidated_units['Status'] = 'Liquidated'
                audit_trail.append(liquidated_units)
                
                # Update Active Inventory
                inv = inv[~liquidated_mask].copy()

                # 3. Global Asset Logic (Vans)
                # First, identify deficits and surpluses for Vans across all locations
                van_reqs = reqs_cleaned[reqs_cleaned['Type'] == 'VAN']
                
                for _, row in van_reqs.iterrows():
                    loc = row['Location']
                    target = row['Target']
                    
                    current_vans = inv[(inv['Location'] == loc) & (inv['Type'] == 'VAN')]
                    deficit = target - len(current_vans)
                    
                    if deficit > 0:
                        # Search for surplus Vans at other locations
                        for other_loc in reqs_cleaned['Location'].unique():
                            if other_loc == loc or deficit <= 0: continue
                            
                            other_target = reqs_cleaned[(reqs_cleaned['Location'] == other_loc) & (reqs_cleaned['Type'] == 'VAN')]['Target'].values[0]
                            other_vans = inv[(inv['Location'] == other_loc) & (inv['Type'] == 'VAN')]
                            
                            surplus = len(other_vans) - other_target
                            if surplus > 0:
                                move_qty = min(surplus, deficit)
                                # Move the oldest vans that are still within age limits
                                vans_to_move = other_vans.sort_values('Age', ascending=False).head(move_qty)['VIN']
                                inv.loc[inv['VIN'].isin(vans_to_move), 'Location'] = loc
                                deficit -= move_qty
                
                # 4. Final Year Count & Leasing Logic
                for _, row in reqs_cleaned.iterrows():
                    loc, v_type, target = row['Location'], row['Type'], row['Target']
                    current_fleet = len(inv[(inv['Location'] == loc) & (inv['Type'] == v_type)])
                    
                    final_deficit = max(0, target - current_fleet)
                    
                    yearly_summary.append({
                        'Year': y,
                        'Location': loc,
                        'Type': v_type,
                        'Leased': final_deficit,
                        'Liquidated': len(liquidated_units[(liquidated_units['Location'] == loc) & (liquidated_units['Type'] == v_type)])
                    })

            # --- Visuals & Reporting ---
            st.divider()
            full_audit_df = pd.concat(audit_trail).drop_duplicates('VIN')
            viz_df = pd.DataFrame(yearly_summary)

            # High Level Cards
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Liquidated", len(full_audit_df))
            c2.metric("Total Leased", viz_df['Leased'].sum())
            c3.metric("Remaining Active Fleet", len(inv))

            # Waterfall / Heatmap Style Chart
            st.subheader("Asset Flow Timeline")
            # Image of a waterfall chart illustrating fleet replacement logic
            
            
            # Pivot data for better visualization
            viz_pivot = viz_df.groupby(['Year', 'Type'])[['Leased', 'Liquidated']].sum().reset_index()
            fig = px.bar(viz_pivot, x="Year", y=["Leased", "Liquidated"], 
                         barmode="group", color_discrete_sequence=["#FF4B4B", "#0068C9"],
                         title="Global Fleet Churn: Leasing vs Liquidation by Year")
            st.plotly_chart(fig, use_container_width=True)

            # Audit Trail Table
            st.subheader("🔍 Searchable Audit Trail")
            search = st.text_input("Filter by VIN or Location")
            if search:
                full_audit_df = full_audit_df[full_audit_df['VIN'].str.contains(search) | full_audit_df['Location'].str.contains(search)]
            st.dataframe(full_audit_df, use_container_width=True)

            # Download
            csv = full_audit_df.to_csv(index=False).encode('utf-8')
            st.download_button("Export Results to CSV", csv, "fleet_simulation.csv", "text/csv")

    except Exception as e:
        st.error(f"Error: {e}. Please ensure Tab A columns match the requirements exactly.")

else:
    st.info("Upload your Excel file to begin. Note: Ensure Tab A has columns: Location, End Year, Max age type A/C/VAN, and Vehicle Count A/C/VAN.")
