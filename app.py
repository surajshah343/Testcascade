import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="Fleet Cascade Optimizer", layout="wide")

## --- UI Logic ---
st.title("🚌 Fleet Lifecycle & Lease Optimizer")
st.markdown("### Strategic Asset Redistribution Simulation")

uploaded_file = st.file_uploader("Upload Fleet Excel File", type=["xlsx"])

if uploaded_file:
    try:
        # Load Tabs
        df_a = pd.read_excel(uploaded_file, sheet_name=0) # Requirements
        df_b = pd.read_excel(uploaded_file, sheet_name=1) # Inventory
        
        st.sidebar.header("Column Mapping")
        
        # Tab A Mapping (Requirements)
        st.sidebar.subheader("Tab A: Requirements")
        loc_col_a = st.sidebar.selectbox("Location Column (Tab A)", df_a.columns)
        type_col_a = st.sidebar.selectbox("Vehicle Type Column (Tab A)", df_a.columns)
        max_age_col = st.sidebar.selectbox("Max Age Column", df_a.columns)
        target_col = st.sidebar.selectbox("Target Count Column", df_a.columns)
        
        # Tab B Mapping (Inventory)
        st.sidebar.subheader("Tab B: Inventory")
        vin_col = st.sidebar.selectbox("VIN Column", df_b.columns)
        type_col_b = st.sidebar.selectbox("Type Column (Tab B)", df_b.columns)
        age_col = st.sidebar.selectbox("Current Age Column", df_b.columns)
        loc_col_b = st.sidebar.selectbox("Location Column (Tab B)", df_b.columns)

        sim_horizon = st.sidebar.slider("Simulation Years", 1, 15, 10)

        if st.sidebar.button("Run Simulation"):
            # Normalize Dataframes for internal logic
            inventory = df_b[[vin_col, type_col_b, age_col, loc_col_b]].copy()
            inventory.columns = ['VIN', 'Type', 'Age', 'Location']
            
            reqs = df_a[[loc_col_a, type_col_a, max_age_col, target_col]].copy()
            reqs.columns = ['Location', 'Type', 'MaxAge', 'Target']

            audit_log = []
            viz_data = []

            for year in range(1, sim_horizon + 1):
                # 1. Aging process
                inventory['Age'] += 1
                
                # 2. Liquidation (Dynamic Matching)
                # Merge current inventory with the specific rules from Tab A
                merged = inventory.merge(reqs, on=['Location', 'Type'], how='left')
                
                # Identify units that hit the age limit
                is_liquidated = merged['Age'] > merged['MaxAge']
                liquidated_units = inventory[is_liquidated].copy()
                liquidated_units['Status'] = 'Liquidated'
                liquidated_units['Year_of_Liquidation'] = year
                audit_log.append(liquidated_units)
                
                # Remove from active inventory
                inventory = inventory[~is_liquidated].copy()

                # 3. Global Asset Logic: Van Redistribution
                for _, row in reqs.iterrows():
                    loc, v_type, target = row['Location'], row['Type'], row['Target']
                    
                    current_count = len(inventory[(inventory['Location'] == loc) & (inventory['Type'] == v_type)])
                    deficit = target - current_count
                    
                    # If deficit exists and asset is a Van, check other locations for surplus
                    if deficit > 0 and "van" in str(v_type).lower():
                        other_locs = inventory[(inventory['Location'] != loc) & (inventory['Type'] == v_type)]
                        
                        for o_loc in other_locs['Location'].unique():
                            if deficit <= 0: break
                            
                            # Check if the other location has more than its target
                            o_target = reqs[(reqs['Location'] == o_loc) & (reqs['Type'] == v_type)]['Target'].values[0]
                            o_count = len(inventory[(inventory['Location'] == o_loc) & (inventory['Type'] == v_type)])
                            
                            surplus = o_count - o_target
                            if surplus > 0:
                                move_qty = min(surplus, deficit)
                                vans_to_move = inventory[(inventory['Location'] == o_loc) & (inventory['Type'] == v_type)].head(move_qty)['VIN']
                                inventory.loc[inventory['VIN'].isin(vans_to_move), 'Location'] = loc
                                deficit -= move_qty
                    
                    # 4. Status Classification: Final Lease Requirement
                    viz_data.append({
                        'Year': year,
                        'Location': loc,
                        'Type': v_type,
                        'Leased': max(0, deficit),
                        'Liquidated': len(liquidated_units[(liquidated_units['Location'] == loc) & (liquidated_units['Type'] == v_type)])
                    })

            # --- Presentation Layer ---
            full_audit = pd.concat(audit_log).drop_duplicates('VIN')
            viz_df = pd.DataFrame(viz_data)

            # Metrics
            m1, m2 = st.columns(2)
            m1.metric("Total Liquidations", len(full_audit))
            m2.metric("Total Leased Units", viz_df['Leased'].sum())

            # Waterfall / Heatmap Chart
            st.subheader("Lease vs Liquidation Timeline")
            # Aggregating by year and location for the visual
            fig_df = viz_df.groupby(['Year', 'Location'])[['Leased', 'Liquidated']].sum().reset_index()
            
            fig = px.bar(fig_df, x="Year", y=["Leased", "Liquidated"], 
                         facet_col="Location", facet_col_wrap=3,
                         title="Asset Cascade by Location",
                         color_discrete_map={"Leased": "#FF4B4B", "Liquidated": "#31333F"})
            st.plotly_chart(fig, use_container_width=True)

            # Audit Trail
            st.subheader("📋 Searchable Audit Trail")
            st.dataframe(full_audit, use_container_width=True)

            # Export
            csv = full_audit.to_csv(index=False).encode('utf-8')
            st.download_button("Download Full Audit CSV", csv, "fleet_audit.csv", "text/csv")

    except Exception as e:
        st.error(f"Error processing simulation: {e}")
        st.info("Check that your Tab A and Tab B contain the correct columns.")

else:
    st.info("Please upload an Excel file to start the simulation.")
