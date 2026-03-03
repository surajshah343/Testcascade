import streamlit as st
import pandas as pd
import plotly.express as px
import io

st.set_page_config(page_title="Global Pool Optimizer", layout="wide")

st.title("🌍 Global Fleet Pool & Optimization Engine")
st.markdown("""
**Strategy:** Treat all inventory as a **Global Pool**. Every year, allocate vehicles to locations by prioritizing the **strictest age constraints first** and assigning the **oldest valid vehicles** to preserve younger assets for future use.
""")

uploaded_file = st.file_uploader("Upload Excel Fleet Data", type=["xlsx", "csv"])

if uploaded_file:
    try:
        # Support both CSV and Excel for flexibility based on your uploads
        if uploaded_file.name.endswith('.csv'):
            st.error("Please upload the original Excel file (.xlsx) containing both Tabs.")
            st.stop()
        else:
            df_a = pd.read_excel(uploaded_file, sheet_name=0) 
            df_b = pd.read_excel(uploaded_file, sheet_name=1)

        # 1. Clean and Prepare Tab A (Requirements)
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
        
        reqs = pd.concat(req_list, ignore_index=True)
        # Clean Types to ensure matching
        reqs['Type'] = reqs['Type'].astype(str).str.upper().str.strip()
        
        # 2. Clean and Prepare Tab B (Global Inventory Pool)
        # We drop 'Location' because it's a global pool!
        inv = df_b[['VINs', 'Current Age', 'Type']].copy()
        inv['Type'] = inv['Type'].astype(str).str.upper().str.strip()
        
        start_year = 2025
        max_end_year = int(reqs['EndYear'].max())

        if st.sidebar.button("Run Global Pool Optimization"):
            
            audit_records = []
            lease_summary = []
            
            # Active Fleet Tracker
            fleet = inv.copy()
            
            progress_bar = st.progress(0)
            
            # 3. Year-by-Year Simulation Loop
            for year in range(start_year, max_end_year + 1):
                # Age progression (if not the first year)
                if year > start_year:
                    fleet['Current Age'] += 1
                
                # We rebuild the pool for this year
                available_pool = fleet.copy()
                
                # Process each Vehicle Type separately
                for v_type in ['A', 'C', 'VAN']:
                    
                    # Get all vehicles of this type currently in the pool
                    type_pool = available_pool[available_pool['Type'] == v_type].copy()
                    
                    # Sort pool descending by age (Oldest first)
                    # We want to assign the oldest possible valid vehicle to save young ones!
                    type_pool = type_pool.sort_values('Current Age', ascending=False)
                    
                    # Get active location requirements for this year and type
                    # Rule: If current year > EndYear, target is 0
                    active_reqs = reqs[(reqs['Type'] == v_type) & (year <= reqs['EndYear'])].copy()
                    
                    # Sort requirements ascending by MaxAge (Strictest constraints first)
                    active_reqs = active_reqs.sort_values('MaxAge', ascending=True)
                    
                    for _, req in active_reqs.iterrows():
                        loc = req['Location']
                        target = req['Target']
                        max_age = req['MaxAge']
                        
                        assigned_count = 0
                        
                        # Try to assign vehicles from the pool
                        for _ in range(int(target)):
                            # Find vehicles in pool that are <= this location's MaxAge
                            valid_vins = type_pool[type_pool['Current Age'] <= max_age]
                            
                            if not valid_vins.empty:
                                # Pick the first one (which is the oldest valid one because we sorted)
                                chosen_vin_idx = valid_vins.index[0]
                                chosen_vehicle = type_pool.loc[chosen_vin_idx]
                                
                                # Log the assignment
                                audit_records.append({
                                    'Calendar_Year': year,
                                    'VINs': chosen_vehicle['VINs'],
                                    'Type': v_type,
                                    'Current Age': chosen_vehicle['Current Age'],
                                    'Assigned_Location': loc,
                                    'Status': 'Assigned'
                                })
                                
                                # Remove from the pool so it can't be used twice
                                type_pool = type_pool.drop(chosen_vin_idx)
                                assigned_count += 1
                            else:
                                # No valid vehicles left for this requirement
                                break
                        
                        # Calculate Leases
                        deficit = int(target) - assigned_count
                        lease_summary.append({
                            'Calendar_Year': year,
                            'Location': loc,
                            'Type': v_type,
                            'Target': target,
                            'Assigned_From_Pool': assigned_count,
                            'New_Leases_Required': max(0, deficit)
                        })

                    # Any vehicles left in the pool that weren't assigned are 'Unassigned/Spare'
                    for _, unassigned in type_pool.iterrows():
                        audit_records.append({
                            'Calendar_Year': year,
                            'VINs': unassigned['VINs'],
                            'Type': v_type,
                            'Current Age': unassigned['Current Age'],
                            'Assigned_Location': 'GLOBAL POOL (Unused)',
                            'Status': 'Unassigned/Spare'
                        })
                        
                progress_bar.progress((year - start_year + 1) / (max_end_year - start_year + 1))

            # --- Presentation & Export ---
            audit_df = pd.DataFrame(audit_records)
            lease_df = pd.DataFrame(lease_summary)

            # Top level metrics
            st.divider()
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Leases Needed (Over Simulation)", lease_df['New_Leases_Required'].sum())
            c2.metric("Total Vehicles in Global Pool", len(inv))
            c3.metric("Simulation End Year", max_end_year)

            # Visualizations
            st.subheader("Global Lease Requirements by Year")
            # Group by year to see the trend
            yearly_leases = lease_df.groupby('Calendar_Year')['New_Leases_Required'].sum().reset_index()
            fig = px.bar(yearly_leases, x='Calendar_Year', y='New_Leases_Required', 
                         title="Total Network Deficit (Leases Triggered)",
                         labels={'New_Leases_Required': 'Leased Units'})
            st.plotly_chart(fig, use_container_width=True)

            # Detailed Lease Table
            st.subheader("📋 Lease Trigger Log")
            st.dataframe(lease_df[lease_df['New_Leases_Required'] > 0].sort_values(['Calendar_Year', 'Location']), use_container_width=True)

            # VIN Audit Trail
            st.subheader("🔍 Global Pool Allocation Audit")
            st.markdown("Shows exactly where the algorithm deployed each VIN year-over-year.")
            search = st.text_input("Filter by VIN or Location")
            
            display_audit = audit_df.copy()
            if search:
                display_audit = display_audit[display_audit['VINs'].astype(str).str.contains(search, case=False) | 
                                              display_audit['Assigned_Location'].astype(str).str.contains(search, case=False)]
                
            st.dataframe(display_audit, use_container_width=True)

            # Export Excel
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                lease_df.to_excel(writer, sheet_name='Lease Schedule', index=False)
                audit_df.to_excel(writer, sheet_name='VIN Allocations', index=False)
            
            st.download_button(
                label="📥 Download Optimal Fleet Allocation (Excel)",
                data=output.getvalue(),
                file_name="Optimal_Global_Pool_Allocation.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    except Exception as e:
        st.error(f"Execution Error: {e}")
        st.info("Ensure the Excel file contains your original Tab A (Location, End Year, Max Age, etc.) and Tab B (VINs, Current Age, Type).")

else:
    st.info("Upload the Fleet Excel Data. The algorithm will automatically pool all assets and distribute them perfectly against the End Year and Max Age bounds.")
