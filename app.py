import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="Fleet Management Optimizer", layout="wide")

## --- UI Header ---
st.title("🚛 Dynamic Fleet & Leasing Optimizer")
st.markdown("Upload your requirements and inventory to simulate multi-year lifecycle optimization.")

## --- File Upload ---
uploaded_file = st.file_uploader("Upload Excel Fleet Data (2 Tabs Required)", type=["xlsx"])

if uploaded_file:
    # Load Tabs
    try:
        df_reqs = pd.read_excel(uploaded_file, sheet_name=0)
        df_inv = pd.read_excel(uploaded_file, sheet_name=1)
        
        st.success("File Loaded Successfully!")
    except Exception as e:
        st.error(f"Error reading tabs: {e}")
        st.stop()

    ## --- Configuration & Column Mapping ---
    # We allow the user to tell us which columns are which to avoid hardcoding errors
    col_map1, col_map2 = st.columns(2)
    
    with col_map1:
        st.subheader("Map Requirement Columns (Tab A)")
        loc_col = st.selectbox("Location Column", df_reqs.columns)
        type_col_req = st.selectbox("Vehicle Type Column (Tab A)", df_reqs.columns)
        max_age_col = st.selectbox("Max Age Limit Column", df_reqs.columns)
        target_col = st.selectbox("Target Count Column", df_reqs.columns)

    with col_map2:
        st.subheader("Map Inventory Columns (Tab B)")
        vin_col = st.selectbox("VIN Column", df_inv.columns)
        type_col_inv = st.selectbox("Vehicle Type Column (Tab B)", df_inv.columns)
        age_col = st.selectbox("Current Age Column", df_inv.columns)
        inv_loc_col = st.selectbox("Current Location Column", df_inv.columns)

    sim_years = st.sidebar.slider("Simulation Duration (Years)", 5, 15, 10)

    if st.sidebar.button("Run Optimization Simulation"):
        
        # Internal standard names to simplify logic
        inv = df_inv[[vin_col, type_col_inv, age_col, inv_loc_col]].copy()
        inv.columns = ['VIN', 'Type', 'Age', 'Location']
        
        reqs = df_reqs[[loc_col, type_col_req, max_age_col, target_col]].copy()
        reqs.columns = ['Location', 'Type', 'MaxAge', 'Target']

        # Tracking variables
        audit_log = []
        yearly_stats = []

        # Start Simulation Loop
        for year in range(1, sim_years + 1):
            # 1. Age Progression
            inv['Age'] += 1
            
            # 2. Identify Liquidations (Units exceeding max age for their specific type/location)
            merged = inv.merge(reqs, on=['Location', 'Type'], how='left')
            liquidated_mask = merged['Age'] > merged['MaxAge']
            
            liquidated_this_year = inv[liquidated_mask].copy()
            liquidated_this_year['Year_of_Liquidation'] = year
            liquidated_this_year['Status'] = 'Liquidated'
            audit_log.append(liquidated_this_year)
            
            # Update active inventory
            inv = inv[~liquidated_mask].copy()

            # 3. Global Asset Redistribution (Vans)
            # Find locations with Van deficits
            for _, req in reqs.iterrows():
                loc = req['Location']
                v_type = req['Type']
                target = req['Target']
                
                current_assets = inv[(inv['Location'] == loc) & (inv['Type'] == v_type)]
                deficit = target - len(current_assets)

                if deficit > 0 and v_type.lower() == 'van':
                    # Try to pull from locations with a surplus of Vans
                    other_vans = inv[(inv['Location'] != loc) & (inv['Type'] == v_type)]
                    
                    # Simple heuristic: move any available van not needed elsewhere
                    # This maximizes lifespan by shifting assets
                    for other_loc in inv[inv['Location'] != loc]['Location'].unique():
                        if deficit <= 0: break
                        
                        loc_target = reqs[(reqs['Location'] == other_loc) & (reqs['Type'] == v_type)]['Target'].values[0]
                        loc_assets = inv[(inv['Location'] == other_loc) & (inv['Type'] == v_type)]
                        
                        surplus = len(loc_assets) - loc_target
                        if surplus > 0:
                            move_qty = min(surplus, deficit)
                            to_move = loc_assets.head(move_qty)['VIN'].values
                            inv.loc[inv['VIN'].isin(to_move), 'Location'] = loc
                            deficit -= move_qty
                
                # 4. Status Classification: Leased
                # If after redistribution there is still a deficit, those are "Leased"
                if deficit > 0:
                    yearly_stats.append({
                        'Year': year,
                        'Location': loc,
                        'Type': v_type,
                        'Leased_Units': deficit,
                        'Liquidated_Units': len(liquidated_this_year[(liquidated_this_year['Location'] == loc) & (liquidated_this_year['Type'] == v_type)])
                    })
                else:
                    yearly_stats.append({
                        'Year': year,
                        'Location': loc,
                        'Type': v_type,
                        'Leased_Units': 0,
                        'Liquidated_Units': len(liquidated_this_year[(liquidated_this_year['Location'] == loc) & (liquidated_this_year['Type'] == v_type)])
                    })

        # Process Results
        full_audit = pd.concat(audit_log).drop_duplicates('VIN')
        summary_df = pd.DataFrame(yearly_stats)

        ## --- Dashboard Visuals ---
        st.divider()
        c1, c2 = st.columns(2)
        c1.metric("Total Liquidations", len(full_audit))
        c2.metric("Total Lease Requirements", summary_df['Leased_Units'].sum())

        ## --- Heatmap / Waterfall Style Chart ---
        st.subheader("Yearly Demand Heatmap (Leased vs. Liquidated)")
        fig_data = summary_df.groupby(['Year', 'Location'])[['Leased_Units', 'Liquidated_Units']].sum().reset_index()
        
        # Pivot for heatmap style view
        fig = px.bar(fig_data, x="Year", y="Leased_Units", color="Location", 
                     title="New Leases Required by Location Over Time",
                     labels={'Leased_Units': 'Units to Lease'})
        st.plotly_chart(fig, use_container_width=True)

        ## --- Audit Trail ---
        st.subheader("🔍 Searchable Audit Trail")
        st.dataframe(full_audit, use_container_width=True)

        ## --- Download ---
        csv = full_audit.to_csv(index=False).encode('utf-8')
        st.download_button("Export Liquidation Schedule (CSV)", csv, "fleet_audit.csv", "text/csv")

else:
    st.info("Awaiting Excel upload. Please ensure your tabs contain Location, Type, and Age data.")
