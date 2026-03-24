terms_of_service = """
## Beautiful Noise — Terms of Service

Last Updated: [DATE]

### The Short Version

Beautiful Noise is a community-driven archive of gig posters from Naarm's live music scene. You keep the rights to anything you upload. By uploading, you give us permission to display it in the archive. Please only upload posters you have the right to share.

---

### 1. Accepting These Terms

By accessing or using Beautiful Noise ("the Service"), you agree to be bound by these Terms. If you do not agree, please do not use the Service.

### 2. What We Do

Beautiful Noise is a living, community-driven archive of posters from Naarm's live music scene. Our aim is to capture and preserve the vibrancy, creativity, and magic behind this art. We provide a platform for users to upload, browse, and celebrate gig poster artwork.

### 3. Your Content

#### What you keep
You retain all copyright and ownership of any content you upload to the Service. We do not claim ownership over your uploads.

#### What you grant us
By uploading content, you grant Beautiful Noise a non-exclusive, royalty-free, worldwide licence to store, display, reproduce, and distribute your content as part of the archive. This licence exists solely for the purpose of operating and presenting the archive.

#### Your responsibility
By uploading a poster, you confirm that:
- You are the creator of the work, **or** you have permission from the creator to share it, **or** you reasonably believe the upload is permitted (e.g. documenting a poster displayed in a public space)
- The content does not infringe on any third party's rights
- The content is a genuine gig poster or related promotional material from Naarm's live music scene

#### What you must not upload
- Content that is illegal, defamatory, or fraudulent
- Content that infringes copyright or other intellectual property rights
- Spam, advertising, or content unrelated to the live music scene
- Private information of any third party

### 4. How Archive Content May Be Used

Content in the Beautiful Noise archive is made available under the **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)** licence, unless otherwise specified by the uploader or copyright holder. This means visitors may share and reference archive content with attribution, but may not use it for commercial purposes.

### 5. Copyright Complaints and Takedowns

If you are a copyright holder and believe content on Beautiful Noise infringes your rights, please contact us at **[EMAIL]** with:
- A description of the copyrighted work
- The URL or file name of the content in question
- Your contact information
- A statement that you are the rights holder or authorised to act on their behalf

We will review all requests promptly and remove infringing content where appropriate.

### 6. Termination

We reserve the right to remove any content or restrict access to the Service at our discretion, particularly in cases of misuse or violation of these Terms.

### 7. Disclaimer of Warranties

The Service is provided "as is" and "as available" without warranties of any kind, either express or implied. We do not guarantee that the Service will be uninterrupted, secure, or error-free.

### 8. Limitation of Liability

To the fullest extent permitted by Australian law, Beautiful Noise and its operators shall not be liable for any indirect, incidental, or consequential damages arising from your use of the Service.

### 9. Changes to These Terms

We may update these Terms from time to time. Changes will be effective when posted to the Service. Continued use of the Service after changes are posted constitutes acceptance of the revised Terms.

### 10. Governing Law

These Terms are governed by the laws of Victoria, Australia.

### 11. Contact

If you have questions about these Terms, please contact us at **[EMAIL]**.
"""
import streamlit as st

# CTA Section
h_cols = st.columns(5)
with h_cols[0]:
    if st.button("ARCHIVE A POSTER", type="primary", use_container_width=True, icon=":material/add:"):
        st.switch_page("upload_page.py")
with h_cols[1]:
    if st.button("VIEW GALLERY", use_container_width=True, icon=":material/chevron_backward:"):
        st.switch_page("gallery_page.py")

st.divider()

st.write(open("tos.md").read())
